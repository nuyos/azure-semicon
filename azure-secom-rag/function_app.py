import os
import json
import logging
import re
from datetime import datetime, timezone, timedelta

import azure.functions as func
from openai import AzureOpenAI
from azure.cosmos import CosmosClient

# ---------------------------------------------------------
# 0. Function App 초기화
# ---------------------------------------------------------
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# ---------------------------------------------------------
# 1. 환경변수 읽기
# ---------------------------------------------------------
OPENAI_ENDPOINT = os.environ["OPENAI_ENDPOINT"]
OPENAI_KEY = os.environ["OPENAI_KEY"]
OPENAI_API_VERSION = os.environ.get("OPENAI_API_VERSION", "2024-05-01-preview")

EMBEDDING_DEPLOYMENT = os.environ["OPENAI_EMBEDDINGS_DEPLOYMENT"]
GPT_DEPLOYMENT = os.environ["OPENAI_GPT_MODEL"]

COSMOS_CONN_STR = os.environ["CosmosDBConnection"]
COSMOS_DB_NAME = os.environ["COSMOSDB_DATABASE"]          # qms
COSMOS_VECTOR_CONTAINER = os.environ["COSMOSDB_CONTAINER"]  # defects-vector

# ---------------------------------------------------------
# 2. 클라이언트 생성
# ---------------------------------------------------------
openai_client = AzureOpenAI(
    azure_endpoint=OPENAI_ENDPOINT,
    api_key=OPENAI_KEY,
    api_version=OPENAI_API_VERSION,
)

cosmos_client = CosmosClient.from_connection_string(COSMOS_CONN_STR)
db = cosmos_client.get_database_client(COSMOS_DB_NAME)
container_vector = db.get_container_client(COSMOS_VECTOR_CONTAINER)


# ---------------------------------------------------------
# 3. 유틸: UTC → KST 예쁘게
# ---------------------------------------------------------
def to_kst_string(event_time_utc: str) -> str:
    """
    Cosmos에 저장된 Event_Time(UTC 문자열)을
    'YYYY-MM-DD HH:MM:SS (KST)' 형식으로 변환.
    """
    if not event_time_utc:
        return "Unknown"

    try:
        # 2025-11-19T08:56:39.141292Z 같은 형태
        dt_utc = datetime.fromisoformat(event_time_utc.replace("Z", "+00:00"))
        kst_tz = timezone(timedelta(hours=9))
        dt_kst = dt_utc.astimezone(kst_tz)
        return dt_kst.strftime("%Y-%m-%d %H:%M:%S (KST)")
    except Exception:
        # 파싱 실패하면 원본 그대로 사용
        return event_time_utc


# ---------------------------------------------------------
# 4. Cosmos DB Trigger: realtime_predictions → defects-vector
# ---------------------------------------------------------
@app.cosmos_db_trigger(
    arg_name="documents",
    container_name="%SOURCE_CONTAINER%",      # realtime_predictions
    database_name="%COSMOSDB_DATABASE%",      # qms
    connection="CosmosDBConnection",
    lease_container_name="leases",
    create_lease_container_if_not_exists=True,
)
def vectorize_defect(documents: func.DocumentList):
    logging.info(f"⚡ [Realtime] {len(documents)}개의 데이터 변경 감지.")

    if not documents:
        return

    for d in documents:
        # Document -> dict 변환
        try:
            doc = d.to_dict()
        except AttributeError:
            doc = d

        try:
            wafer_id = (
                doc.get("Wafer_ID")
                or doc.get("wafer_id")
                or doc.get("id")
                or "Unknown"
            )
            line_id = doc.get("Line_ID", "Unknown")
            event_time = doc.get("Event_Time", "Unknown")
            actual_label = doc.get("Actual_Label")
            predicted_label = doc.get("Predicted_Label")
            predicted_prob = doc.get("Predicted_Probability")

            logging.info(
                f"▶️ vectorize_defect: wafer_id={wafer_id}, "
                f"line_id={line_id}, event_time={event_time}, "
                f"actual={actual_label}, pred={predicted_label}, prob={predicted_prob}"
            )

            pretty_time_kst = to_kst_string(event_time)

            # 벡터화용 텍스트
            text_to_embed = (
                f"{pretty_time_kst} {line_id} 공정에서 발생한 불량 웨이퍼 {wafer_id}. "
                f"실제 라벨={actual_label}, 예측 라벨={predicted_label}, "
                f"불량 확률={predicted_prob}."
            )

            # OpenAI 임베딩 생성
            emb_resp = openai_client.embeddings.create(
                input=text_to_embed,
                model=EMBEDDING_DEPLOYMENT,
            )
            vector = emb_resp.data[0].embedding
            logging.info(f"✅ 임베딩 생성 완료 (길이={len(vector)})")

            # defects-vector 에 저장할 문서
            new_doc = {
                "id": wafer_id,
                "wafer_id": wafer_id,
                "line_id": line_id,
                "event_time": event_time,           # 원본 UTC
                "event_time_kst": pretty_time_kst,  # 보기 좋은 시간 문자열
                "actual_label": actual_label,
                "predicted_label": predicted_label,
                "predicted_probability": predicted_prob,
                "content": text_to_embed,
                "vector": vector,
            }

            container_vector.upsert_item(new_doc)
            logging.info(f"✅ [Saved] defects-vector upsert 완료: id={wafer_id}")

        except Exception as e:
            logging.error(
                f"❌ vectorize_defect error for doc id={doc.get('id')}: {e}",
                exc_info=True,
            )


# ---------------------------------------------------------
# 5. 질문 파싱 (모드 + 라인 + 시간범위)
# ---------------------------------------------------------
def extract_time_filter(question: str):
    """
    '최근 1시간', '최근 30분', '최근 2일' 패턴을 찾아서
    (from_time_iso, 설명문구) 를 리턴. 없으면 (None, None).
    """
    q = question.replace(" ", "")
    m = re.search(r"최근(\d+)(분|시간|일)", q)
    if not m:
        return None, None

    num = int(m.group(1))
    unit = m.group(2)

    if unit == "분":
        delta = timedelta(minutes=num)
        unit_kr = f"{num}분"
    elif unit == "시간":
        delta = timedelta(hours=num)
        unit_kr = f"{num}시간"
    else:  # "일"
        delta = timedelta(days=num)
        unit_kr = f"{num}일"

    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    from_utc = now_utc - delta
    # Cosmos 의 event_time 형식과 맞추기 위해 초까지만 사용
    from_iso = from_utc.strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
    return from_iso, unit_kr


def parse_question_mode(question: str):
    """
    mode:
      - count_total         : 전체 불량 개수
      - count_per_line      : A/B 라인별 불량 개수
      - count_single_line   : 특정 라인(A/B)만 개수
      - list                : 목록 / 전부 보여줘
      - default             : 일반 RAG
    return: (mode, line_filter, from_time_iso, time_desc)
    """
    q_lower = question.lower()

    # 라인 필터
    line_filter = None
    if "a-line" in q_lower or "a라인" in q_lower or "a 라인" in q_lower:
        line_filter = "A-Line"
    elif "b-line" in q_lower or "b라인" in q_lower or "b 라인" in q_lower:
        line_filter = "B-Line"

    # 시간 필터
    from_time_iso, time_desc = extract_time_filter(question)

    # 목록 / 리스트
    list_keywords = ["목록", "리스트", "전부 보여", "다 보여", "전체 보여"]
    if any(k in question for k in list_keywords):
        return "list", line_filter, from_time_iso, time_desc

    # 개수 관련
    count_keywords = ["불량 수", "불량수", "개수", "몇개", "몇 개", "몇 건", "건수"]
    is_count = any(k in question for k in count_keywords)

    # "라인별" 이 들어가면 라인별 개수
    if is_count and ("라인별" in question or "line별" in question or "라인 별" in question):
        return "count_per_line", None, from_time_iso, time_desc

    # 특정 라인에 대한 개수
    if is_count and line_filter is not None:
        return "count_single_line", line_filter, from_time_iso, time_desc

    # 전체 개수
    if is_count:
        return "count_total", None, from_time_iso, time_desc

    # 그 외는 RAG
    return "default", line_filter, from_time_iso, time_desc


# ---------------------------------------------------------
# 6. HTTP Trigger: RAG + 집계/목록 모드
# ---------------------------------------------------------
@app.route(route="chat_rag", auth_level=func.AuthLevel.ANONYMOUS)
def chat_rag(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("🔍 RAG / 집계 검색 요청 수신.")

    # ---- 요청 파라미터 ----
    try:
        body = req.get_json()
        question = body.get("question")
        if not question:
            return func.HttpResponse("Missing 'question'", status_code=400)
    except ValueError:
        return func.HttpResponse("Invalid JSON", status_code=400)

    try:
        mode, line_filter, from_time_iso, time_desc = parse_question_mode(question)
        logging.info(
            f"질문 파싱 결과: mode={mode}, line_filter={line_filter}, "
            f"from_time={from_time_iso}"
        )

        # ================================
        # A. 개수 계산 모드 (COUNT)
        # ================================
        if mode in ["count_total", "count_per_line", "count_single_line"]:
            where_clauses = []
            params = []

            # 시간 필터
            if from_time_iso:
                where_clauses.append("c.event_time >= @from_time")
                params.append({"name": "@from_time", "value": from_time_iso})

            # 특정 라인 필터
            if mode == "count_single_line" and line_filter:
                where_clauses.append("c.line_id = @line")
                params.append({"name": "@line", "value": line_filter})

            where_sql = ""
            if where_clauses:
                where_sql = " WHERE " + " AND ".join(where_clauses)

            # 쿼리 작성
            if mode == "count_per_line":
                # 라인별 그룹
                query = (
                    "SELECT c.line_id, COUNT(1) AS defect_count "
                    "FROM c" + where_sql +
                    " GROUP BY c.line_id"
                )
            else:
                # 전체 또는 단일 라인
                query = "SELECT VALUE COUNT(1) FROM c" + where_sql

            logging.info(f"[COUNT MODE] query={query}, params={params}")

            items = list(
                container_vector.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True,
                )
            )

            # 응답 메시지 구성
            if mode == "count_per_line":
                if not items:
                    msg = "불량 웨이퍼 데이터가 없습니다."
                    if time_desc:
                        msg = f"{time_desc} 동안 {msg}"
                    return func.HttpResponse(
                        json.dumps({"answer": msg}),
                        mimetype="application/json",
                    )

                # line_id 들이 이미 A-Line / B-Line 이라 가정
                parts = []
                total = 0
                for row in items:
                    line = row.get("line_id")
                    count = int(row.get("defect_count") or 0)
                    total += count
                    parts.append(f"{line}: {count}개")

                prefix = "라인별 불량 웨이퍼 개수는 다음과 같습니다.\n"
                if time_desc:
                    prefix = f"{time_desc} 기준 " + prefix

                answer = prefix + " / ".join(parts) + f"\n\n총 불량 개수: {total}개"
                return func.HttpResponse(
                    json.dumps({"answer": answer}),
                    mimetype="application/json",
                )

            else:
                # count_total 또는 count_single_line
                count_value = int(items[0]) if items else 0

                if mode == "count_single_line" and line_filter:
                    prefix = f"{line_filter} 공정의 불량 웨이퍼 개수는 "
                else:
                    prefix = "전체 불량 웨이퍼 개수는 "

                if time_desc:
                    prefix = f"{time_desc} 기준 {prefix}"

                answer = f"{prefix}{count_value}개 입니다."
                return func.HttpResponse(
                    json.dumps({"answer": answer}),
                    mimetype="application/json",
                )

        # ================================
        # B. 목록 모드 (LIST)
        # ================================
        if mode == "list":
            where_clauses = []
            params = []

            if line_filter:
                where_clauses.append("c.line_id = @line")
                params.append({"name": "@line", "value": line_filter})

            if from_time_iso:
                where_clauses.append("c.event_time >= @from_time")
                params.append({"name": "@from_time", "value": from_time_iso})

            where_sql = ""
            if where_clauses:
                where_sql = " WHERE " + " AND ".join(where_clauses)

            query = (
                "SELECT c.wafer_id, c.line_id, c.event_time_kst, "
                "c.actual_label, c.predicted_label, c.predicted_probability "
                "FROM c" + where_sql +
                " ORDER BY c.event_time DESC"
            )

            items = list(
                container_vector.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True,
                )
            )

            if not items:
                if line_filter:
                    msg = f"{line_filter} 공정에서 불량 웨이퍼 데이터를 찾을 수 없습니다."
                else:
                    msg = "불량 웨이퍼 데이터가 아직 저장되어 있지 않습니다."
                if from_time_iso and time_desc:
                    msg = f"{time_desc} 기준 " + msg
                return func.HttpResponse(
                    json.dumps({"answer": msg}),
                    mimetype="application/json",
                )

            MAX_ITEMS = 50
            shown = items[:MAX_ITEMS]
            total = len(items)

            lines = []
            header = "불량인 웨이퍼의 목록은 다음과 같습니다:\n"
            if time_desc:
                header = f"{time_desc} 기준 " + header
            if line_filter:
                header = f"{line_filter} 공정에서 " + header

            lines.append(header)
            for i, d in enumerate(shown, start=1):
                prob = float(d.get("predicted_probability") or 0) * 100
                lines.append(
                    f"{i}. 웨이퍼 {d.get('wafer_id')} ({d.get('line_id')}) - "
                    f"시간={d.get('event_time_kst')}, "
                    f"실제 라벨={d.get('actual_label')}, "
                    f"예측 라벨={d.get('predicted_label')}, "
                    f"불량 확률={round(prob, 2)}%"
                )

            if total > MAX_ITEMS:
                lines.append(
                    f"\n※ 총 {total}개 중 상위 {MAX_ITEMS}개만 표시했습니다."
                )

            answer = "\n".join(lines)
            return func.HttpResponse(
                json.dumps({"answer": answer}),
                mimetype="application/json",
            )

        # ================================
        # C. 일반 질문 → 벡터 RAG
        # ================================
        q_vec = openai_client.embeddings.create(
            input=question,
            model=EMBEDDING_DEPLOYMENT,
        ).data[0].embedding

        query = (
            "SELECT TOP 10 c.wafer_id, c.line_id, c.event_time_kst, "
            "c.actual_label, c.predicted_label, c.predicted_probability, c.content "
            "FROM c ORDER BY VectorDistance(c.vector, @vector, true)"
        )

        results = container_vector.query_items(
            query=query,
            parameters=[{"name": "@vector", "value": q_vec}],
            enable_cross_partition_query=True,
        )

        docs = list(results)

        if not docs:
            context_text = "관련된 불량 데이터를 찾을 수 없습니다."
        else:
            ctx_lines = []
            ctx_lines.append("검색된 유사 불량 사례:\n")
            for d in docs:
                prob = float(d.get("predicted_probability") or 0) * 100
                ctx_lines.append(
                    f"- [{d.get('line_id')}] 웨이퍼 {d.get('wafer_id')} "
                    f"({d.get('event_time_kst')}) | "
                    f"실제={d.get('actual_label')}, "
                    f"예측={d.get('predicted_label')}, "
                    f"불량확률={round(prob, 2)}%"
                )
            context_text = "\n".join(ctx_lines)

        system_prompt = (
            "너는 반도체 공정(A-Line, B-Line) 불량 분석 전문가야.\n"
            "아래 [Context]에 있는 불량 데이터를 기반으로만 사용자의 질문에 답변해.\n"
            "데이터에 없는 내용은 절대 지어내지 말고, "
            "\"정보가 없습니다\" 또는 \"데이터 상으로는 확인되지 않습니다\" 라고 답해.\n\n"
            f"[Context]\n{context_text}"
        )

        chat_resp = openai_client.chat.completions.create(
            model=GPT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        )

        answer = chat_resp.choices[0].message.content
        return func.HttpResponse(
            json.dumps({"answer": answer}),
            mimetype="application/json",
        )

    except Exception as e:
        logging.error(f"Error in chat_rag: {e}", exc_info=True)
        return func.HttpResponse(
            f"Internal Server Error: {e}",
            status_code=500,
        )
