"""
=====================================================================
 해시 검색 알고리즘 서버 (Google Cloud Run / Python Flask)
=====================================================================
 - 충돌 해결 방식 : 개방 주소법(Open Addressing) 중 '선형 탐사(Linear Probing)'
 - 해시 함수      : 제산(나눗셈) 방법  h(k) = k mod m
                     * 정수 키   → 그대로 사용
                     * 문자열 키 → 각 문자의 유니코드 값 합(Σ ord(c))을 정수로 변환 후 사용
 - 삭제 처리      : 삭제된 슬롯을 비우면 탐사 체인이 끊어지므로
                     'DELETED(묘비, tombstone)' 표시를 남긴다.
 - 제공 기능      : init, hash_value, search, add, remove, dump
 - 모든 응답에는 클라이언트가 도형으로 단계별 재생할 수 있도록
   'steps'(단계 목록)와 테이블 스냅샷(table_before / table)이 포함된다.

 [주의] 해시 테이블은 서버 메모리에 저장된다.
   Cloud Run은 인스턴스가 여러 개 뜨면 상태가 나뉘므로
   배포 시 --max-instances=1 옵션을 사용하고,
   gunicorn 워커도 1개(스레드 여러 개)로 실행한다. (Dockerfile 참고)
=====================================================================
"""

import os
import re
import time
import threading

from flask import Flask, request, jsonify
from flask_cors import CORS

# ---------------------------------------------------------------------
# Flask 앱 & CORS 설정
# ---------------------------------------------------------------------
app = Flask(__name__)

# 허용할 출처(Origin)는 환경변수 ALLOWED_ORIGINS 로 지정 (쉼표 구분)
#   예) ALLOWED_ORIGINS="https://script.google.com,https://*.googleusercontent.com"
# 지정하지 않으면 모든 출처(*) 허용 → 수업/실습용 기본값
#   ※ GAS의 UrlFetchApp 호출은 '서버→서버' 요청이라 CORS의 영향을 받지 않지만,
#     브라우저(index.html)에서 Cloud Run을 직접 호출하는 경우를 위해 설정해 둔다.
_origins = os.environ.get("ALLOWED_ORIGINS", "*")
CORS(
    app,
    resources={r"/*": {"origins": [o.strip() for o in _origins.split(",")]}},
    methods=["GET", "POST", "OPTIONS"],       # 허용 HTTP 메서드
    allow_headers=["Content-Type"],           # 허용 요청 헤더
    max_age=3600,                             # Preflight(OPTIONS) 결과 캐시 시간(초)
)

# 테이블 크기 제한 (시각화가 가능한 범위로 제한)
MIN_SIZE, MAX_SIZE, DEFAULT_SIZE = 1, 50, 11


# ---------------------------------------------------------------------
# 슬롯 상태 표시용 센티널(sentinel) 객체
#   EMPTY   : 한 번도 사용되지 않은 빈 슬롯 → 탐색은 여기서 멈춘다
#   DELETED : 삭제된 슬롯(묘비)          → 탐색은 계속 진행, 삽입은 재사용 가능
# ---------------------------------------------------------------------
class _Sentinel:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return self.name


EMPTY = _Sentinel("EMPTY")
DELETED = _Sentinel("DELETED")


def normalize_key(value):
    """
    클라이언트에서 받은 키를 정규화한다.
      - 앞뒤 공백 제거
      - 정수 형태("15", "-3")면 int 로 변환
      - 그 외는 문자열 그대로 (최대 20자)
    """
    if value is None:
        raise ValueError("키(key)가 비어 있습니다.")
    s = str(value).strip()
    if s == "":
        raise ValueError("키(key)가 비어 있습니다.")
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if len(s) > 20:
        raise ValueError("문자열 키는 20자 이하로 입력하세요.")
    return s


class HashTable:
    """선형 탐사(Linear Probing) 해시 테이블"""

    def __init__(self, size=DEFAULT_SIZE):
        self.lock = threading.Lock()   # 동시 요청으로 인한 상태 꼬임 방지
        self.init(size)

    # -----------------------------------------------------------------
    # 내부 유틸리티
    # -----------------------------------------------------------------
    def snapshot(self):
        """현재 테이블 상태를 JSON 직렬화 가능한 리스트로 반환"""
        result = []
        for i, slot in enumerate(self.table):
            if slot is EMPTY:
                result.append({"index": i, "state": "empty", "key": None})
            elif slot is DELETED:
                result.append({"index": i, "state": "deleted", "key": None})
            else:
                result.append({"index": i, "state": "used", "key": slot})
        return result

    def stats(self):
        """테이블 통계: 크기, 저장 개수, 묘비 개수, 적재율(α = n / m)"""
        deleted = sum(1 for s in self.table if s is DELETED)
        return {
            "size": self.size,
            "count": self.count,
            "deleted": deleted,
            "load_factor": round(self.count / self.size, 3),
        }

    def _hash(self, key):
        """
        해시 함수 h(k) = k mod m 계산 + 계산 과정을 단계(step)로 반환
          - 문자열 : Σ ord(c) 로 정수화한 뒤 mod 연산
        """
        if isinstance(key, int):
            raw = key
            formula = f"{key}"
        else:
            codes = [ord(c) for c in key]
            raw = sum(codes)
            formula = " + ".join(f"'{c}'({ord(c)})" for c in key) + f" = {raw}"

        index = raw % self.size     # 파이썬의 %는 음수에도 0 ~ m-1 을 반환
        step = {
            "type": "hash",
            "status": "hash",
            "key": key,
            "raw": raw,
            "index": index,
            "formula": formula,
            "desc": f"해시 계산: h({key!r}) = {raw} mod {self.size} = {index}",
        }
        return index, step

    # -----------------------------------------------------------------
    # 1) init : 테이블 초기화  - 시간 복잡도 O(m)
    # -----------------------------------------------------------------
    def init(self, size=DEFAULT_SIZE):
        size = int(size)
        if not (MIN_SIZE <= size <= MAX_SIZE):
            raise ValueError(f"테이블 크기는 {MIN_SIZE} ~ {MAX_SIZE} 사이여야 합니다.")
        self.size = size
        self.table = [EMPTY] * size   # 모든 슬롯을 EMPTY 로 채움
        self.count = 0
        steps = [{
            "type": "init", "status": "init", "index": None, "mutate": True,
            "desc": f"크기 {size}의 빈 해시 테이블 생성 (h(k) = k mod {size})",
        }]
        return True, f"테이블을 크기 {size}로 초기화했습니다.", steps, 0

    # -----------------------------------------------------------------
    # 2) hash_value : 키의 해시값만 계산  - O(1)
    # -----------------------------------------------------------------
    def hash_value(self, key):
        index, step = self._hash(key)
        return True, f"h({key!r}) = {index}", [step], 0

    # -----------------------------------------------------------------
    # 3) search : 키 탐색  - 평균 O(1), 최악 O(m)
    #    홈 주소(h(k))부터 한 칸씩 이동하며
    #      - 같은 키   → 성공
    #      - EMPTY     → 실패 (그 뒤로는 있을 수 없음)
    #      - DELETED   → 건너뛰고 계속
    #      - 다른 키   → 충돌, 다음 칸으로
    # -----------------------------------------------------------------
    def search(self, key):
        home, hstep = self._hash(key)
        steps, probes = [hstep], 0

        for i in range(self.size):
            idx = (home + i) % self.size          # 선형 탐사: (h(k) + i) mod m
            probes += 1
            slot = self.table[idx]

            if slot is EMPTY:
                steps.append({"type": "probe", "status": "empty", "index": idx,
                              "desc": f"[{idx}] 빈 슬롯 → 키 {key!r} 없음 (탐색 실패)"})
                return False, f"키 {key!r}을(를) 찾지 못했습니다. (탐사 {probes}회)", steps, probes
            if slot is DELETED:
                steps.append({"type": "probe", "status": "skip-deleted", "index": idx,
                              "desc": f"[{idx}] 삭제 표시(묘비) → 건너뛰고 다음 칸"})
                continue
            if slot == key:
                steps.append({"type": "probe", "status": "found", "index": idx,
                              "desc": f"[{idx}] {slot!r} == {key!r} → 탐색 성공!"})
                return True, f"키 {key!r}을(를) 인덱스 {idx}에서 찾았습니다. (탐사 {probes}회)", steps, probes

            steps.append({"type": "probe", "status": "collision", "index": idx,
                          "desc": f"[{idx}] {slot!r} ≠ {key!r} → 충돌, 다음 칸 [{(idx + 1) % self.size}]"})

        steps.append({"type": "end", "status": "notfound", "index": None,
                      "desc": "테이블 전체를 탐사했지만 키가 없습니다."})
        return False, f"키 {key!r}을(를) 찾지 못했습니다. (탐사 {probes}회)", steps, probes

    # -----------------------------------------------------------------
    # 4) add : 키 삽입  - 평균 O(1), 최악 O(m)
    #    - 탐사 중 첫 번째로 만난 DELETED 위치를 기억해 두었다가 재사용
    #    - 중복 키 확인을 위해 EMPTY 를 만날 때까지는 계속 탐사
    # -----------------------------------------------------------------
    def add(self, key):
        home, hstep = self._hash(key)
        steps, probes = [hstep], 0

        if self.count >= self.size:
            steps.append({"type": "end", "status": "full", "index": None,
                          "desc": "테이블이 가득 찼습니다 (α = 1). 삽입 불가."})
            return False, "테이블이 가득 차서 삽입할 수 없습니다.", steps, probes

        first_tomb = None   # 처음 만난 묘비 위치
        target = None       # 최종 삽입 위치

        for i in range(self.size):
            idx = (home + i) % self.size
            probes += 1
            slot = self.table[idx]

            if slot is EMPTY:
                target = first_tomb if first_tomb is not None else idx
                steps.append({"type": "probe", "status": "empty", "index": idx,
                              "desc": f"[{idx}] 빈 슬롯 발견"
                                      + (f" → 앞서 찾은 묘비 [{first_tomb}] 재사용" if first_tomb is not None else "")})
                break
            if slot is DELETED:
                if first_tomb is None:
                    first_tomb = idx
                steps.append({"type": "probe", "status": "skip-deleted", "index": idx,
                              "desc": f"[{idx}] 묘비 → 삽입 후보로 기억, 중복 확인을 위해 계속 탐사"})
                continue
            if slot == key:
                steps.append({"type": "probe", "status": "duplicate", "index": idx,
                              "desc": f"[{idx}] 이미 같은 키 {key!r}가 존재 → 삽입 취소"})
                return False, f"키 {key!r}는 이미 존재합니다.", steps, probes

            steps.append({"type": "probe", "status": "collision", "index": idx,
                          "desc": f"[{idx}] {slot!r}가 차지 → 충돌, 다음 칸 [{(idx + 1) % self.size}]"})

        # 빈 칸 없이 한 바퀴를 돌았지만 묘비가 있었던 경우
        if target is None:
            target = first_tomb

        self.table[target] = key
        self.count += 1
        steps.append({"type": "write", "status": "inserted", "index": target, "mutate": True,
                      "desc": f"[{target}]에 키 {key!r} 저장 완료"})
        return True, f"키 {key!r}를 인덱스 {target}에 삽입했습니다. (탐사 {probes}회)", steps, probes

    # -----------------------------------------------------------------
    # 5) remove : 키 삭제  - 평균 O(1), 최악 O(m)
    #    탐색 후 찾은 슬롯을 EMPTY 가 아닌 DELETED(묘비)로 표시한다.
    #    (EMPTY 로 바꾸면 그 뒤에 이어진 키들을 찾지 못하게 됨)
    # -----------------------------------------------------------------
    def remove(self, key):
        found, _, steps, probes = self.search(key)
        if not found:
            return False, f"키 {key!r}가 없어 삭제할 수 없습니다.", steps, probes

        idx = steps[-1]["index"]   # search 의 마지막 단계 = 찾은 위치
        self.table[idx] = DELETED
        self.count -= 1
        steps.append({"type": "write", "status": "removed", "index": idx, "mutate": True,
                      "desc": f"[{idx}] 키 {key!r} 삭제 → 묘비(DELETED)로 표시"})
        return True, f"키 {key!r}를 인덱스 {idx}에서 삭제했습니다.", steps, probes

    # -----------------------------------------------------------------
    # 6) dump : 테이블 전체 출력  - O(m)
    # -----------------------------------------------------------------
    def dump(self):
        steps = []
        for i, slot in enumerate(self.table):
            if slot is EMPTY:
                text = "비어 있음"
            elif slot is DELETED:
                text = "삭제됨(묘비)"
            else:
                text = f"키 {slot!r} (홈 주소 {self._hash(slot)[0]})"
            steps.append({"type": "dump", "status": "dump", "index": i, "desc": f"[{i}] {text}"})
        return True, f"테이블 덤프: {self.count}개 저장 / 크기 {self.size}", steps, self.size


def complexity_info(action, probes, alpha):
    """
    연산별 시간 복잡도와, 선형 탐사의 이론적 기대 탐사 횟수(Knuth)를 반환
      - 성공 탐색 기대 횟수 ≈ ½ (1 + 1/(1-α))
      - 실패 탐색 기대 횟수 ≈ ½ (1 + 1/(1-α)²)
    """
    table = {
        "init":       {"best": "O(m)", "average": "O(m)", "worst": "O(m)"},
        "hash_value": {"best": "O(1)", "average": "O(1)", "worst": "O(1)"},
        "search":     {"best": "O(1)", "average": "O(1)", "worst": "O(m)"},
        "add":        {"best": "O(1)", "average": "O(1)", "worst": "O(m)"},
        "remove":     {"best": "O(1)", "average": "O(1)", "worst": "O(m)"},
        "dump":       {"best": "O(m)", "average": "O(m)", "worst": "O(m)"},
    }
    info = dict(table[action])
    info["actual_probes"] = probes
    if alpha < 1:
        info["expected_success"] = round(0.5 * (1 + 1 / (1 - alpha)), 2)
        info["expected_fail"] = round(0.5 * (1 + 1 / (1 - alpha) ** 2), 2)
    else:
        info["expected_success"] = None   # α = 1 이면 발산
        info["expected_fail"] = None
    info["note"] = "m = 테이블 크기, α = 적재율(n/m). α가 1에 가까울수록 군집(clustering)으로 탐사 횟수가 급증"
    return info


# 서버 전역 해시 테이블 (인스턴스 1개 기준)
hash_table = HashTable(DEFAULT_SIZE)


# ---------------------------------------------------------------------
# 라우트
# ---------------------------------------------------------------------
@app.get("/")
@app.get("/health")
def health():
    """서버 동작 상태 확인용 (클라이언트의 '서버 상태' 표시에 사용)"""
    return jsonify({"ok": True, "service": "hash-search", "time": time.time(),
                    "stats": hash_table.stats()})


@app.post("/hash")
def hash_api():
    """
    단일 엔드포인트로 모든 연산을 처리한다.
    요청(JSON) 예:
      {"action": "init",       "size": 11}
      {"action": "hash_value", "key": "apple"}
      {"action": "add",        "key": 25}
      {"action": "search",     "key": 25}
      {"action": "remove",     "key": 25}
      {"action": "dump"}
    """
    started = time.perf_counter()
    body = request.get_json(silent=True) or {}
    action = str(body.get("action", "")).strip()

    handlers = {"init", "hash_value", "search", "add", "remove", "dump"}
    if action not in handlers:
        return jsonify({"ok": False, "error": f"알 수 없는 action: {action!r}",
                        "allowed": sorted(handlers)}), 400

    try:
        with hash_table.lock:                       # 연산 중 다른 요청 차단
            table_before = hash_table.snapshot()    # 연산 전 상태 (단계 재생용)

            if action == "init":
                ok, msg, steps, probes = hash_table.init(body.get("size", DEFAULT_SIZE))
            elif action == "dump":
                ok, msg, steps, probes = hash_table.dump()
            else:
                key = normalize_key(body.get("key"))
                ok, msg, steps, probes = getattr(hash_table, action)(key)

            stats = hash_table.stats()
            result = {
                "ok": ok,
                "action": action,
                "message": msg,
                "steps": steps,
                "table_before": table_before,
                "table": hash_table.snapshot(),          # 연산 후 상태
                "stats": stats,
                "complexity": complexity_info(action, probes, stats["load_factor"]),
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        return jsonify(result)

    except ValueError as e:      # 잘못된 입력
        return jsonify({"ok": False, "action": action, "error": str(e)}), 400
    except Exception as e:       # 예기치 못한 서버 오류
        return jsonify({"ok": False, "action": action, "error": f"서버 오류: {e}"}), 500


if __name__ == "__main__":
    # 로컬 테스트용: python main.py  →  http://localhost:8080
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
