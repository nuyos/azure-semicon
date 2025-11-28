import gradio as gr
import requests
import json
import logging
import socket

# 🚨 Azure Function이 로컬에서 실행 중인 주소
CHAT_RAG_ENDPOINT = "http://localhost:7071/api/chat_rag"


# ============================
# 1. 백엔드 호출 함수
# ============================
def rag_chat(message, history):
    """
    Gradio 메시지를 받아 로컬 Azure Function (chat_rag) API를 호출하고 응답을 받습니다.
    """
    try:
        response = requests.post(
            CHAT_RAG_ENDPOINT,
            json={"question": message},
            timeout=30,
        )

        if response.status_code == 200:
            result = response.json()
            return result.get("answer", "죄송합니다. 데이터베이스에서 관련 정보를 찾지 못했습니다.")
        else:
            return (
                f"Error: Function API 호출 실패.\n"
                f"상태 코드: {response.status_code}\n응답: {response.text}"
            )

    except requests.exceptions.ConnectionError:
        return (
            "Error: Azure Function이 로컬에서 실행 중이 아닙니다.\n"
            "VS Code에서 F5를 눌러 함수 앱을 다시 실행한 뒤, "
            "다시 시도해 주세요."
        )
    except Exception as e:
        logging.error(f"알 수 없는 오류: {str(e)}")
        return f"알 수 없는 오류가 발생했습니다: {str(e)}"


# ============================
# 2. 밝은 반도체 테마 (Theme + CSS)
# ============================

semi_theme = gr.themes.Soft()

semi_css = """
/* 전체 배경: 밝은 하늘색 → 흰색 그라데이션, 화면 꽉 채우기 */
body {
    margin: 0;
    padding: 0;
}
.gradio-container {
    min-height: 100vh !important;
    padding: 1.5rem 2rem 2rem 2rem !important;
    box-sizing: border-box;
    background: linear-gradient(180deg, #e0f4ff 0%, #ffffff 40%, #ffffff 100%);
}

/* 제목 중앙 정렬 + 가독성 높게 */
.gradio-container h1 {
    text-align: center;
    font-weight: 800;
    letter-spacing: 0.06em;
    color: #0f172a;
    margin-bottom: 0.4rem;
}

/* 부제목 */
.gradio-container p {
    text-align: center;
    color: #4b5563;
    margin-top: 0;
    margin-bottom: 0.8rem;
}

/* 상단 예시 버튼 영역 */
.examples.svelte-1gfkn6j, .examples {
    justify-content: center;
}

/* 예시 버튼 스타일 (네이비 배경 + 흰 글자) */
button.example {
    background: #020617 !important;
    color: #f9fafb !important;
    border-radius: 999px !important;
    border: none !important;
    padding: 0.45rem 1.2rem !important;
    font-weight: 600 !important;
}

/* Chatbot 패널을 화면 대부분을 차지하도록 */
.gr-chatbot {
    height: 65vh !important;
}

/* 채팅 말풍선 - 사용자 */
.gr-chatbot .message.user {
    background: #020617 !important;
    color: #f9fafb !important;
    border-radius: 18px 18px 4px 18px !important;
}

/* 채팅 말풍선 - 봇 */
.gr-chatbot .message.bot {
    background: #ffffff !important;
    color: #111827 !important;
    border-radius: 18px 18px 18px 4px !important;
    border: 1px solid #e5e7eb !important;
}

/* 입력 박스 */
textarea, .gr-textbox textarea {
    background: #020617 !important;
    color: #f9fafb !important;
    border-radius: 999px !important;
    border: none !important;
}

/* 전송 버튼(종이비행기) */
button.primary {
    border-radius: 999px !important;
}

/* 푸터 여백 제거 */
footer {
    margin-top: 0 !important;
}
"""


# ============================
# 3. Gradio ChatInterface
# ============================
demo = gr.ChatInterface(
    fn=rag_chat,
    type="messages",  # openai-style role/content 포맷 사용
    title="공정 이상탐지 RAG 시스템",
    description="Cosmos DB에 저장된 벡터 기반 A-Line / B-Line 공정의 불량 데이터를 이용해 이상 상황을 분석합니다.",
    chatbot=gr.Chatbot(
        height=550,  # px 단위, 처음부터 꽤 크게
        label="A-Line / B-Line 공정 이상 로그",
        type="messages",
    ),
    theme=semi_theme,
    css=semi_css,
    examples=[
        "최근 30분 A, B 라인의 불량수",
        "A라인 전체 불량 웨이퍼 목록과 불량 확률 보여줘",
        "B라인에서 가장 위험도가 높은 불량 사례 5개 요약해줘",
        "최근 1시간 동안 A라인과 B라인의 불량 개수를 비교해줘",
    ],
)


# ============================
# 4. IP 출력 헬퍼
# ============================
def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 실제로 접속하진 않지만, 라우팅 정보로 로컬 IP를 알아냄
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


# ============================
# 5. 실행
# ============================
if __name__ == "__main__":
    host = "0.0.0.0"
    port = 7870
    ip = get_local_ip()

    print("\n🚀 공정 이상탐지 RAG UI 서버 시작")
    print(f"   ▶ 로컬 브라우저:  http://127.0.0.1:{port}")
    print(f"   ▶ 로컬 브라우저:  http://localhost:{port}")
    print(f"   ▶ 같은 네트워크 다른 PC/폰:  http://{ip}:{port}")
    print("")

    # share=True 로 바꾸면 gradio 공개 URL도 만들 수 있음(네트워크/방화벽 환경에 따라 실패할 수 있음)
    demo.launch(
        server_name=host,
        server_port=port,
        share=False,
    )
