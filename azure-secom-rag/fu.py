import azure.functions as func
import logging
import os
import json
from openai import AzureOpenAI
from azure.cosmos import CosmosClient, PartitionKey

# ----------------------------------------------------------------
# 1. Azure OpenAI 클라이언트 초기화 (공용)
# ----------------------------------------------------------------
openai_client = AzureOpenAI(
    azure_endpoint=os.environ["OPENAI_ENDPOINT"],
    api_key=os.environ["OPENAI_KEY"],
    api_version=os.environ.get("OPENAI_API_VERSION", "2024-05-01-preview")
)
EMBEDDING_DEPLOYMENT = os.environ["OPENAI_EMBEDDINGS_DEPLOYMENT"]
GPT_DEPLOYMENT = os.environ["OPENAI_GPT_MODEL"]

# ----------------------------------------------------------------
# 2. Cosmos DB 클라이언트 초기화 (공용) - [최종 수정]
# 'CosmosDBConnection' (연결 문자열) 하나만 사용하도록 수정
# ----------------------------------------------------------------
cosmos_client = CosmosClient.from_connection_string(
    conn_str=os.environ["CosmosDBConnection"]
)
db = cosmos_client.get_database_client(os.environ["COSMOSDB_DATABASE"])
container_vector = db.get_container_client(os.environ["COSMOSDB_CONTAINER"]) 

# ----------------------------------------------------------------
# 3. Azure Function 앱 초기화
# ----------------------------------------------------------------
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


# ----------------------------------------------------------------
# 함수 1: 'defects_hot' 감시 -> 벡터 변환 -> 'defects-vector'에 저장
# ----------------------------------------------------------------
@app.cosmos_db_trigger(arg_name="documents", 
                       container_name="defects_hot",
                       database_name="qms", 
                       connection="CosmosDBConnection", 
                       lease_container_name="leases",
                       create_lease_container_if_not_exists=True) 
def vectorize_defect(documents: func.DocumentList):
    logging.info(f"Cosmos DB Trigger: {len(documents)} new documents found in defects_hot.")
    
    for doc in documents:
        try:
            defect_data = json.loads(doc.to_json())
            
            # 1. 벡터화를 위한 텍스트 생성
            text_to_embed = f"""
            Defect Report ID: {defect_data.get('id')}
            Line: {defect_data.get('line_id')}
            Wafer ID: {defect_data.get('wafer_id')}
            Pass/Fail: {defect_data.get('PassFail')}
            """
            
            # 2. OpenAI 임베딩 모델 호출
            embedding_response = openai_client.embeddings.create(
                input=text_to_embed,
                model=EMBEDDING_DEPLOYMENT
            )
            
            # 3. 벡터 결과를 원본 데이터에 추가 (Cosmos DB Vector Policy에 맞춤)
            defect_data['contentVector'] = embedding_response.data[0].embedding
            
            # 4. 벡터가 추가된 문서를 'defects-vector' 컨테이너에 저장
            container_vector.upsert_item(body=defect_data)
            logging.info(f"Successfully vectorized and saved document ID: {defect_data.get('id')}")

        except Exception as e:
            logging.error(f"Error processing document {doc.get('id')}: {str(e)}")


# ----------------------------------------------------------------
# 함수 2: Gradio의 질문을 받아 RAG로 답변
# ----------------------------------------------------------------
@app.route(route="chat_rag")
def chat_rag(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger (chat_rag) processed a request.')

    try:
        req_body = req.get_json()
        question = req_body.get('question')
        if not question:
            return func.HttpResponse("Missing 'question' in request body", status_code=400)
    except ValueError:
        return func.HttpResponse("Invalid JSON format", status_code=400)

    try:
        # 1. 질문을 벡터로 변환 (검색용)
        question_embedding = openai_client.embeddings.create(
            input=question,
            model=EMBEDDING_DEPLOYMENT
        ).data[0].embedding

        # 2. Cosmos DB에서 벡터 검색 (R: Retrieval) - [수정된 쿼리]
        query = """
            SELECT TOP 3 c.id, c.line_id, c.wafer_id, c.PassFail
            FROM c
            ORDER BY VectorDistance(c.contentVector, @question_vector, true, {"distanceFunction": "cosine"})
        """
        
        results = container_vector.query_items(
            query=query,
            parameters=[
                {"name": "@question_vector", "value": question_embedding}
            ],
            enable_cross_partition_query=True
        )
        
        context_documents = list(results)
        
        # 3. 검색된 데이터를 LLM에게 전달할 "컨텍스트"로 조합
        context = "Search Results (Defect Data):\n"
        if not context_documents:
            context = "No relevant defect data found in Cosmos DB."
        else:
            for doc in context_documents:
                context += f"- {json.dumps(doc)}\n"

        system_prompt = f"""
        You are an expert assistant for semiconductor manufacturing. 
        Analyze the user's question based on the following retrieved defect data (Search Results).
        Provide a clear and concise answer based *only* on this data. Do not make up information.

        --- CONTEXT (Search Results) ---
        {context}
        ---------------------------------
        """
        
        # 4. LLM 호출 (G: Generation)
        chat_response = openai_client.chat.completions.create(
            model=GPT_DEPLOYMENT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question}
            ]
        )
        
        answer = chat_response.choices[0].message.content

        # 5. Gradio에 최종 답변 전송
        return func.HttpResponse(json.dumps({"answer": answer}), mimetype="application/json")

    except Exception as e:
        logging.error(f"Error in chat_rag: {str(e)}")
        return func.HttpResponse(f"Internal Server Error: {str(e)}", status_code=500)