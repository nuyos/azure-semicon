# Azure 기반 반도체 공정 실시간 불량 탐지 & 데이터 인텔리전스 플랫폼

Real-Time Streaming · ML Prediction · Medallion Architecture · RAG Chatbot

본 프로젝트는 반도체 공정에서 발생하는 대규모 센서 데이터를 실시간으로 수집·분석하고 Azure Native 서비스를 활용해 End-to-End 데이터 파이프라인, 실시간 알림, 생성형 AI 기반 분석 서비스를 구축하는 것을 목표로 합니다.

---

## 1. 프로젝트 배경 (Background & Why)

반도체 제조 공정은 수백 개의 센서가 실시간으로 데이터를 생성합니다.  
공정 품질을 유지하기 위해서는 이상 징후를 빠르게 감지하는 시스템이 필수적입니다.

### 기존 문제점
- 실시간 모니터링 부족 → 사후 대응 중심
- 시스템 간 데이터 파편화 → 통합 분석 어려움
- 고정된 규칙 기반의 한계 → 정확도 제한
- 불량률이 극히 낮아 불균형 데이터 문제가 심각함

이를 해결하기 위해 실시간 스트리밍 기반 자동화 이상 탐지 플랫폼을 설계하였습니다.

---

## 2. 데이터셋 설명

### 데이터 구성
- Feature 590개
- 총 1567개 샘플
- 라벨 비율: 정상 97% / 불량 3%
- 시간 정보 없음
- Wafer_ID 단위 그룹 구조

### 데이터의 어려움(Why)
- 극단적 불균형 → 모델 학습 난이도 높음
- 고차원 데이터 → 차원축소 필요
- 센서 간 상관성 높음 → Feature Selection 필수
- 시간축 없음 → 누적 기반 특징 설계 필요

### 해결 전략
- Borderline-SMOTE로 불균형 해소
- PCA + Random Forest Selection으로 차원축소
- GroupShuffleSplit으로 데이터 누수 방지
- Threshold 튜닝으로 Sensitivity 극대화

---

## 3. 전체 아키텍처
```
[SENSOR SIMULATOR]
↓ (Event Hub)
[Azure Stream Analytics]
↓
┌───────────────┬────────────────┐
│ ADLS Bronze │ ADLS Silver │
└───────────────┴────────────────┘
↓
[Azure ML: Training → AKS Endpoint]
↓
[Cosmos DB]
↓
[Function App → Logic App → Teams Alert]
↓
[Power BI Dashboard] [RAG Chatbot]
```

---

## 4. 기술 스택

### Azure
- Event Hub
- Stream Analytics
- Azure Machine Learning
- Azure Kubernetes Service (AKS)
- Cosmos DB
- Logic Apps
- Function Apps
- Power BI
- Key Vault, Managed Identity, Private Endpoint

### Machine Learning
- Borderline-SMOTE
- PCA
- Random Forest Feature Selection
- XGBoost / Logistic Regression
- Threshold Optimization

### Application
- RAG(ChatGPT 기반 Retrieval QA)
- Gradio UI
- Teams Webhook Alert

---

## 5. 데이터 파이프라인 상세

### (1) 실시간 데이터 수집·적재
- Python Sensor Simulator → Event Hub
- Stream Analytics → ADLS Bronze/Silver 저장
- Fail/Anomaly 데이터는 Cosmos DB에 별도 저장

### (2) Machine Learning
- 불균형 처리(Borderline-SMOTE)
- 전처리(Sclaer, PCA, RF Selection)
- 모델 학습 및 검증
- 임계값 재조정(Threshold tuning)

#### 모델 성능(최종)
- Sensitivity: **95.45%**
- Specificity: **94.23%**
- 최적 Threshold: **0.345**

### (3) 실시간 추론 & 알림
- AKS Endpoint 기반 실시간 추론
- Cosmos DB Change Feed Trigger → Function App 실행
- Logic App → Teams 실시간 알림 발송

---

## 6. RAG 기반 AI 챗봇

### 주요 기능
- 자연어 기반 불량/결측 조회
- Gold/Silver 데이터 근거 기반 답변
- Stream 데이터 기반 실시간 질의응답
- Gradio UI 제공

---

## 7. Power BI 시각화

- 실시간 센서 스트림 반영
- Pass/Fail 현황 모니터링
- 라인별 센서 이상 분포
- 모델 평가 지표 시각화

---

## 8. 보안 & 비용 관리 (FinOps / SecOps)

### 비용 관리
- Azure 월간 예산 80만 원 내 관리
- 모든 Compute 리소스 사용 후 즉시 중지
- 리소스 단위·용량 최적화

### 보안 관리
- Managed Identity 기반 인증
- Key Vault로 모든 중요 정보 암호화
- Private Endpoint 기반 내부망 통신

---

## 9. 주요 트러블슈팅

### 1) 모델 용량 13GB → 배포 불가
- 전처리 파이프라인 경량화
- 더미 Feature 제거
- joblib으로 최종 모델 압축

### 2) 데이터 누수(Data Leakage)
- 랜덤 분할 → GroupShuffleSplit으로 개선
- 검증 로직 추가하여 재발 방지

### 3) AzureML v1/v2 Endpoint 호환성 문제
- AKS Endpoint로 통합 배포하여 ASA 연동 성공

---

## 10. 심사위원 피드백

### 긍정적 평가
1. 기업 관점의 문제 정의와 방향성이 우수함  
2. 프로젝트 흐름이 논리적이고 Azure 활용 전략이 성숙함  
3. 주제 적합성과 구현력이 높음  

### 개선 사항
1. 데이터셋 설명·Why 요소를 더 강조하면 좋음  
2. 구조도 가독성을 더 높이면 발표 퀄리티 상승  

(본 README는 위 피드백을 반영하여 재작성됨)

---

## 11. 프로젝트 구조
```
azure-semicon/
├── README.md
├── docs/
│   ├── architecture.png
│   ├── pipeline_overview.png
│   └── presentation.pdf
├── dataset/
│   └── README.md
├── src/
│   ├── pipeline/
│   ├── ml/
│   ├── endpoint/
│   ├── function_app/
│   └── chatbot/
├── demo/
│   ├── teams_alert.mp4
│   └── rag_demo.mp4
└── requirements.txt
```


---

## 12. 결론 & 향후 발전 방향

### 성과
- Azure 기반 End-to-End AI 플랫폼 구축
- 실시간 스트리밍 + ML 서빙 + RAG 챗봇 통합 구현
- 반도체 공정 시나리오 기반 파이프라인 완성

### 향후 계획
- 대규모 데이터 기반 딥러닝 모델 실험
- SHAP 기반 Explainable AI 적용
- 데이터 품질 개선을 통한 RAG 정확도 향상


