from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)

# [CORS 설정] 구글 앱스 스크립트(GAS) 등 외부 클라이언트의 요청을 허용합니다.
CORS(app)

@app.route('/binary-search', methods=['POST'])
def binary_search():
    """
    이진 검색 알고리즘 수행 API
    - 입력: JSON { "target": 숫자, "array": [정렬된 숫자 리스트] }
    - 출력: 각 탐색 단계별 상태(low, high, mid, mid_val 등)와 최종 성공 여부
    """
    try:
        data = request.get_json()
        if not data or 'target' not in data or 'array' not in data:
            return jsonify({'error': '유효하지 않은 요청 데이터입니다. target과 array가 필요합니다.'}), 400

        target = int(data['target'])
        array = data['array']
        
        # 이진 검색 수행을 위해 배열이 정렬되어 있는지 확인 및 정렬
        array.sort()

        low = 0
        high = len(array) - 1
        steps = []  # 시각화를 위해 각 단계의 상태 기록
        found_index = -1

        # 이진 검색 알고리즘 시작
        while low <= high:
            mid = (low + high) // 2
            mid_val = array[mid]

            # 현재 단계의 탐색 정보를 기록
            steps.append({
                'step': len(steps) + 1,
                'low': low,
                'high': high,
                'mid': mid,
                'mid_val': mid_val,
                'status': 'checking'
            })

            if mid_val == target:
                found_index = mid
                steps[-1]['status'] = 'found'
                break
            elif mid_val < target:
                low = mid + 1
            else:
                high = mid - 1

        return jsonify({
            'success': True,
            'array': array,
            'target': target,
            'found_index': found_index,
            'total_steps': len(steps),
            'steps': steps,
            'time_complexity': 'O(log N)',
            'space_complexity': 'O(1)'
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Cloud Run은 PORT 환경변수를 주입합니다.
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
