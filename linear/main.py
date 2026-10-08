import os
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
# 구글 앱스 스크립트(GAS) 웹 앱에서 전송하는 CORS 요청 허용
CORS(app)

@app.route('/linear_search', methods=['POST'])
def linear_search():
    """
    선형 검색(Linear Search) 수행 API Endpoint
    
    [입력 데이터 JSON Format]
    {
        "array": [10, 20, 30, 40, 50],
        "target": 30
    }
    
    [시간 복잡도]
    - 최선(Best Case): O(1) - 첫 번째 원소에서 찾은 경우
    - 최악(Worst Case): O(N) - 배열의 끝까지 찾거나 존재하지 않는 경우
    - 평균(Average Case): O(N)
    
    [공간 복잡도]
    - O(1) : 추가적인 메모리 공간을 거의 사용하지 않음
    """
    try:
        data = request.get_json()
        
        # 입력값 유효성 검직
        if not data or 'array' not in data or 'target' not in data:
            return jsonify({
                'status': 'error',
                'message': '유효하지 않은 요청 데이터입니다. array와 target을 포함해야 합니다.'
            }), 400

        array = data['array']
        target = data['target']

        # 알고리즘 동작 단계(Steps) 기록용 리스트
        steps = []
        found_index = -1

        # 선형 검색 알고리즘 수행: 0번 인덱스부터 순차적으로 비교
        for index, value in enumerate(array):
            is_match = (value == target)
            
            # 각 단계를 기록하여 클라이언트 시각화에 활용
            steps.append({
                'step': index + 1,
                'current_index': index,
                'current_value': value,
                'target': target,
                'is_match': is_match
            })
            
            # 타겟을 발견하면 반복 중단
            if is_match:
                found_index = index
                break

        # 처리 결과 응답 구성
        response_payload = {
            'status': 'success',
            'result': {
                'found': found_index != -1,
                'found_index': found_index,
                'total_steps': len(steps),
                'complexity': {
                    'time_complexity': 'O(N)',
                    'space_complexity': 'O(1)',
                    'best_case': 'O(1)',
                    'worst_case': 'O(N)'
                },
                'steps': steps
            }
        }
        return jsonify(response_payload), 200

    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'서버 내부 오류 발생: {str(e)}'
        }), 500

if __name__ == '__main__':
    # Cloud Run 기본 포트(8080) 설정 반영
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
