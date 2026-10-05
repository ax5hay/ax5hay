<div align="center">

# Akshay Bajpai

**`In thrust we trust.`**

I build reliable, robust software systems, AI or otherwise.<br/>
The kind that holds under load, states its own assumptions, and fails loud instead of silent.

[![Website](https://img.shields.io/badge/www-akshaybajpai.com-1a1a1e?style=for-the-badge&labelColor=ece6d9&color=8c2f24)](https://www.akshaybajpai.com)
[![X](https://img.shields.io/badge/@ax5hay-0b0b0f?style=for-the-badge&logo=x&logoColor=white)](https://x.com/ax5hay)
[![Email](https://img.shields.io/badge/contact-0b0b0f?style=for-the-badge&logo=maildotru&logoColor=white)](mailto:contact@akshaybajpai.com)

</div>

---

<div align="center"><i>Thrust is cheap. Controlled thrust is the whole job.</i></div>

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#15151c','primaryTextColor':'#f3ede0','primaryBorderColor':'#d8bd85','lineColor':'#6f6a5f','fontSize':'15px'}}}%%
flowchart LR
  F(["ideas and raw data"]) --> T["THRUST<br/>ship the thing"]
  T --> C{"control<br/>surfaces"}
  C --> O["orchestration"]
  C --> S["safety and guardrails"]
  C --> D["schema that<br/>refuses bad data"]
  C --> M["observability"]
  O --> R(["TRUST<br/>holds under load, in prod"])
  S --> R
  D --> R
  M --> R
  classDef thrust fill:#8c2f24,stroke:#d8bd85,stroke-width:1.5px,color:#f6f1e6;
  classDef hub fill:#14141a,stroke:#d8bd85,stroke-width:1.5px,color:#d8bd85;
  classDef node fill:#15151c,stroke:#3a3a42,color:#e8e3d6;
  classDef seed fill:#0f0f14,stroke:#3a3a42,color:#b4b0a4;
  class T,R thrust;
  class C hub;
  class O,S,D,M node;
  class F seed;
```

I design systems the way you'd design a propulsion stack: **thrust is easy, control is the work.**
Most of what I build sits in the unglamorous middle: the orchestration, the safety layer, the
schema that refuses bad data, the job queue that survives a restart. Shipping a demo is thrust.
Keeping it upright in production is trust.

I work across the stack but gravitate toward **AI systems that have to behave**: LLM assistance
that stays inside guardrails, pipelines that turn mess into structured truth, and vision/edge
workloads that run where the data actually lives.

---

## What I'm flying right now

<div align="center"><sub>A map of what I build, and the domains it falls into.</sub></div>

```mermaid
%%{init: {'theme':'base','themeVariables':{'primaryColor':'#15151c','primaryTextColor':'#f3ede0','primaryBorderColor':'#d8bd85','lineColor':'#6f6a5f'}}}%%
flowchart TB
  ME(("Akshay<br/>Bajpai"))
  ME --> AI["AI systems<br/>and LLMs"]
  ME --> CV["computer vision<br/>and edge"]
  ME --> DP["data platforms<br/>and pipelines"]
  ME --> WP["web, product<br/>and sites"]
  AI --> AURIXA["AURIXA"]
  AI --> GHDA["GHDA-SaaS"]
  AI --> OCR["OCR-LLM-DIST"]
  CV --> VIG["Vigilix"]
  CV --> DADM["DADM"]
  CV --> FS["FlowState"]
  DP --> AIDA["AIDA"]
  DP --> RS["RestroScraper"]
  WP --> MST["MirrorState"]
  WP --> SITE["akshaybajpai.com"]
  classDef core fill:#8c2f24,stroke:#d8bd85,stroke-width:2px,color:#f6f1e6;
  classDef dom fill:#14141a,stroke:#d8bd85,stroke-width:1.3px,color:#d8bd85;
  classDef proj fill:#15151c,stroke:#3a3a42,color:#e8e3d6;
  class ME core;
  class AI,CV,DP,WP dom;
  class AURIXA,GHDA,OCR,VIG,DADM,FS,AIDA,RS,MST,SITE proj;
```

<table>
<tr>
<td width="50%" valign="top">

**[AURIXA](https://github.com/ax5hay/AURIXA)** · care-ops platform<br/>
<sub>Multi-tenant conversational care operations: governed LLM assistance over one orchestration and safety layer. `TypeScript` · `Python` · `Next.js` · `FastAPI` · `Fastify`</sub>

</td>
<td width="50%" valign="top">

**[AIDA](https://github.com/ax5hay/AIDA)** · health intelligence<br/>
<sub>Postgres → Prisma → NestJS → Next.js analytics with optional LLM narration. The UI never opens a DB connection. `TypeScript` · `Prisma`</sub>

</td>
</tr>
<tr>
<td width="50%" valign="top">

**[DADM](https://github.com/ax5hay/DADM-Aiximius)** · defensive AI mesh<br/>
<sub>Edge anomaly detection, federated learning, defense-ontology graph. Offline-first, zero-trust, air-gap capable. `Rust` · `Python` · `ONNX` · `Neo4j`</sub>

</td>
<td width="50%" valign="top">

**[Vigilix](https://github.com/ax5hay/Vigilix)** · AI video wall<br/>
<sub>Live multi-camera wall for security ops: RTSP ingest, YOLO overlays, incident alerts. `React` · `FastAPI` · `Python`</sub>

</td>
</tr>
<tr>
<td width="50%" valign="top">

**[GHDA](https://github.com/ax5hay/GHDA-SaaS)** · gov health automation<br/>
<sub>Turns messy, multilingual survey reports into structured JSON, gap analysis, and compliance insight. `FastAPI` · `Fastify` · `OCR`</sub>

</td>
<td width="50%" valign="top">

**[akshaybajpai.com](https://github.com/ax5hay/akshaybajpai.com)** · this person, as a drawing set<br/>
<sub>A personal site issued as numbered architectural sheets, re-issuable in three CSS-only states. `Next.js 15` · zero 3D runtime deps</sub>

</td>
</tr>
</table>

<sub>More in the <a href="https://github.com/ax5hay?tab=repositories">repository index</a>: lead CRMs, job-application automation, OCR and local-LLM document chat, a behavioral-evidence OS, and a pile of ML notebooks from earlier flight tests.</sub>

---

## The stack I actually touch

<sub>Every tool below appears in a shipped repo. Pulled by scanning every dependency manifest across all my repositories.</sub>

<table>
<tr>
<td valign="top"><b>Languages</b></td>
<td>
<img src="https://img.shields.io/badge/TypeScript-3178C6?style=flat-square&logo=typescript&logoColor=white" alt="TypeScript" />
<img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python" />
<img src="https://img.shields.io/badge/Rust-000000?style=flat-square&logo=rust&logoColor=white" alt="Rust" />
<img src="https://img.shields.io/badge/C%23-512BD4?style=flat-square&logo=dotnet&logoColor=white" alt="C#" />
<img src="https://img.shields.io/badge/JavaScript-F7DF1E?style=flat-square&logo=javascript&logoColor=black" alt="JavaScript" />
<img src="https://img.shields.io/badge/SQL-025E8C?style=flat-square&logo=postgresql&logoColor=white" alt="SQL" />
<img src="https://img.shields.io/badge/Bash-4EAA25?style=flat-square&logo=gnubash&logoColor=white" alt="Bash" />
<img src="https://img.shields.io/badge/Cypher-008CC1?style=flat-square&logo=neo4j&logoColor=white" alt="Cypher" />
</td>
</tr>
<tr>
<td valign="top"><b>Frontend & UI</b></td>
<td>
<img src="https://img.shields.io/badge/Next.js-000000?style=flat-square&logo=nextdotjs&logoColor=white" alt="Next.js" />
<img src="https://img.shields.io/badge/React-20232A?style=flat-square&logo=react&logoColor=61DAFB" alt="React" />
<img src="https://img.shields.io/badge/Angular-DD0031?style=flat-square&logo=angular&logoColor=white" alt="Angular" />
<img src="https://img.shields.io/badge/Astro-BC52EE?style=flat-square&logo=astro&logoColor=white" alt="Astro" />
<img src="https://img.shields.io/badge/Vite-646CFF?style=flat-square&logo=vite&logoColor=white" alt="Vite" />
<img src="https://img.shields.io/badge/Tailwind_CSS-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white" alt="Tailwind CSS" />
<img src="https://img.shields.io/badge/Sass-CC6699?style=flat-square&logo=sass&logoColor=white" alt="Sass" />
<img src="https://img.shields.io/badge/Radix_UI-161618?style=flat-square&logo=radixui&logoColor=white" alt="Radix UI" />
<img src="https://img.shields.io/badge/Framer_Motion-0055FF?style=flat-square&logo=framer&logoColor=white" alt="Framer Motion" />
<img src="https://img.shields.io/badge/TanStack_Query-FF4154?style=flat-square&logo=reactquery&logoColor=white" alt="TanStack Query" />
<img src="https://img.shields.io/badge/Zustand-443E38?style=flat-square" alt="Zustand" />
<img src="https://img.shields.io/badge/Storybook-FF4785?style=flat-square&logo=storybook&logoColor=white" alt="Storybook" />
</td>
</tr>
<tr>
<td valign="top"><b>Dataviz</b></td>
<td>
<img src="https://img.shields.io/badge/Recharts-22B5BF?style=flat-square" alt="Recharts" />
<img src="https://img.shields.io/badge/D3.js-F9A03C?style=flat-square&logo=d3dotjs&logoColor=white" alt="D3.js" />
<img src="https://img.shields.io/badge/Apache_ECharts-AA344D?style=flat-square&logo=apacheecharts&logoColor=white" alt="Apache ECharts" />
</td>
</tr>
<tr>
<td valign="top"><b>Backend & APIs</b></td>
<td>
<img src="https://img.shields.io/badge/Node.js-5FA04E?style=flat-square&logo=nodedotjs&logoColor=white" alt="Node.js" />
<img src="https://img.shields.io/badge/NestJS-E0234E?style=flat-square&logo=nestjs&logoColor=white" alt="NestJS" />
<img src="https://img.shields.io/badge/Fastify-000000?style=flat-square&logo=fastify&logoColor=white" alt="Fastify" />
<img src="https://img.shields.io/badge/Express-000000?style=flat-square&logo=express&logoColor=white" alt="Express" />
<img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI" />
<img src="https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white" alt="Flask" />
<img src="https://img.shields.io/badge/.NET-512BD4?style=flat-square&logo=dotnet&logoColor=white" alt=".NET" />
<img src="https://img.shields.io/badge/Uvicorn-2A2A2A?style=flat-square" alt="Uvicorn" />
<img src="https://img.shields.io/badge/Socket.IO-010101?style=flat-square&logo=socketdotio&logoColor=white" alt="Socket.IO" />
<img src="https://img.shields.io/badge/SignalR-512BD4?style=flat-square" alt="SignalR" />
<img src="https://img.shields.io/badge/OpenAPI-6BA539?style=flat-square&logo=openapiinitiative&logoColor=white" alt="OpenAPI" />
<img src="https://img.shields.io/badge/Zod-3E67B1?style=flat-square&logo=zod&logoColor=white" alt="Zod" />
<img src="https://img.shields.io/badge/BullMQ-FF4500?style=flat-square" alt="BullMQ" />
</td>
</tr>
<tr>
<td valign="top"><b>AI, ML & data science</b></td>
<td>
<img src="https://img.shields.io/badge/PyTorch-EE4C2C?style=flat-square&logo=pytorch&logoColor=white" alt="PyTorch" />
<img src="https://img.shields.io/badge/TensorFlow-FF6F00?style=flat-square&logo=tensorflow&logoColor=white" alt="TensorFlow" />
<img src="https://img.shields.io/badge/Keras-D00000?style=flat-square&logo=keras&logoColor=white" alt="Keras" />
<img src="https://img.shields.io/badge/scikit--learn-F7931E?style=flat-square&logo=scikitlearn&logoColor=white" alt="scikit-learn" />
<img src="https://img.shields.io/badge/NumPy-013243?style=flat-square&logo=numpy&logoColor=white" alt="NumPy" />
<img src="https://img.shields.io/badge/pandas-150458?style=flat-square&logo=pandas&logoColor=white" alt="pandas" />
<img src="https://img.shields.io/badge/SciPy-8CAAE6?style=flat-square&logo=scipy&logoColor=black" alt="SciPy" />
<img src="https://img.shields.io/badge/Matplotlib-11557C?style=flat-square" alt="Matplotlib" />
<img src="https://img.shields.io/badge/Jupyter-F37626?style=flat-square&logo=jupyter&logoColor=white" alt="Jupyter" />
</td>
</tr>
<tr>
<td valign="top"><b>Computer vision & docs</b></td>
<td>
<img src="https://img.shields.io/badge/OpenCV-5C3EE8?style=flat-square&logo=opencv&logoColor=white" alt="OpenCV" />
<img src="https://img.shields.io/badge/YOLO_%2F_Ultralytics-0B2545?style=flat-square" alt="YOLO / Ultralytics" />
<img src="https://img.shields.io/badge/MediaPipe-0097A7?style=flat-square" alt="MediaPipe" />
<img src="https://img.shields.io/badge/dlib-008000?style=flat-square" alt="dlib" />
<img src="https://img.shields.io/badge/supervision-6706CE?style=flat-square" alt="supervision" />
<img src="https://img.shields.io/badge/ONNX-005CED?style=flat-square&logo=onnx&logoColor=white" alt="ONNX" />
<img src="https://img.shields.io/badge/EasyOCR-2D7DD2?style=flat-square" alt="EasyOCR" />
<img src="https://img.shields.io/badge/Tesseract-4E7F28?style=flat-square" alt="Tesseract" />
<img src="https://img.shields.io/badge/PyMuPDF-B5121B?style=flat-square" alt="PyMuPDF" />
</td>
</tr>
<tr>
<td valign="top"><b>LLMs, RAG & NLP</b></td>
<td>
<img src="https://img.shields.io/badge/LangChain-1C3C3C?style=flat-square&logo=langchain&logoColor=white" alt="LangChain" />
<img src="https://img.shields.io/badge/OpenAI-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI" />
<img src="https://img.shields.io/badge/Ollama-000000?style=flat-square&logo=ollama&logoColor=white" alt="Ollama" />
<img src="https://img.shields.io/badge/LM_Studio-4A4A52?style=flat-square" alt="LM Studio" />
<img src="https://img.shields.io/badge/Weaviate-00C8A0?style=flat-square&logo=weaviate&logoColor=white" alt="Weaviate" />
<img src="https://img.shields.io/badge/RAG-8C2F24?style=flat-square" alt="RAG" />
<img src="https://img.shields.io/badge/NLP-3A5A40?style=flat-square" alt="NLP" />
</td>
</tr>
<tr>
<td valign="top"><b>Data & storage</b></td>
<td>
<img src="https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white" alt="PostgreSQL" />
<img src="https://img.shields.io/badge/Redis-FF4438?style=flat-square&logo=redis&logoColor=white" alt="Redis" />
<img src="https://img.shields.io/badge/SQLite-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite" />
<img src="https://img.shields.io/badge/Neo4j-4581C3?style=flat-square&logo=neo4j&logoColor=white" alt="Neo4j" />
<img src="https://img.shields.io/badge/MinIO-C72E49?style=flat-square&logo=minio&logoColor=white" alt="MinIO" />
<img src="https://img.shields.io/badge/Prisma-2D3748?style=flat-square&logo=prisma&logoColor=white" alt="Prisma" />
<img src="https://img.shields.io/badge/Drizzle_ORM-C5F74F?style=flat-square&logo=drizzle&logoColor=black" alt="Drizzle ORM" />
<img src="https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat-square&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy" />
<img src="https://img.shields.io/badge/Alembic-6BA81E?style=flat-square" alt="Alembic" />
</td>
</tr>
<tr>
<td valign="top"><b>Infra, CI/CD & cloud</b></td>
<td>
<img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker" />
<img src="https://img.shields.io/badge/Turborepo-EF4444?style=flat-square&logo=turborepo&logoColor=white" alt="Turborepo" />
<img src="https://img.shields.io/badge/pnpm-F69220?style=flat-square&logo=pnpm&logoColor=white" alt="pnpm" />
<img src="https://img.shields.io/badge/Nginx-009639?style=flat-square&logo=nginx&logoColor=white" alt="Nginx" />
<img src="https://img.shields.io/badge/Terraform-844FBA?style=flat-square&logo=terraform&logoColor=white" alt="Terraform" />
<img src="https://img.shields.io/badge/Helm-0F1689?style=flat-square&logo=helm&logoColor=white" alt="Helm" />
<img src="https://img.shields.io/badge/AWS-232F3E?style=flat-square&logo=amazonwebservices&logoColor=white" alt="AWS" />
<img src="https://img.shields.io/badge/GitHub_Actions-2088FF?style=flat-square&logo=githubactions&logoColor=white" alt="GitHub Actions" />
</td>
</tr>
<tr>
<td valign="top"><b>Observability & security</b></td>
<td>
<img src="https://img.shields.io/badge/Prometheus-E6522C?style=flat-square&logo=prometheus&logoColor=white" alt="Prometheus" />
<img src="https://img.shields.io/badge/Grafana-F46800?style=flat-square&logo=grafana&logoColor=white" alt="Grafana" />
<img src="https://img.shields.io/badge/Loki-F46800?style=flat-square" alt="Loki" />
<img src="https://img.shields.io/badge/OpenTelemetry-000000?style=flat-square&logo=opentelemetry&logoColor=white" alt="OpenTelemetry" />
<img src="https://img.shields.io/badge/Pino-687634?style=flat-square&logo=pino&logoColor=white" alt="Pino" />
<img src="https://img.shields.io/badge/Loguru-00979D?style=flat-square" alt="Loguru" />
<img src="https://img.shields.io/badge/Trivy-1904DA?style=flat-square&logo=trivy&logoColor=white" alt="Trivy" />
<img src="https://img.shields.io/badge/CodeQL-2088FF?style=flat-square&logo=github&logoColor=white" alt="CodeQL" />
</td>
</tr>
<tr>
<td valign="top"><b>Testing & quality</b></td>
<td>
<img src="https://img.shields.io/badge/Vitest-6E9F18?style=flat-square&logo=vitest&logoColor=white" alt="Vitest" />
<img src="https://img.shields.io/badge/Jest-C21325?style=flat-square&logo=jest&logoColor=white" alt="Jest" />
<img src="https://img.shields.io/badge/pytest-0A9EDC?style=flat-square&logo=pytest&logoColor=white" alt="pytest" />
<img src="https://img.shields.io/badge/Playwright-2EAD33?style=flat-square&logo=playwright&logoColor=white" alt="Playwright" />
<img src="https://img.shields.io/badge/Testing_Library-E33332?style=flat-square&logo=testinglibrary&logoColor=white" alt="Testing Library" />
<img src="https://img.shields.io/badge/ESLint-4B32C3?style=flat-square&logo=eslint&logoColor=white" alt="ESLint" />
<img src="https://img.shields.io/badge/Prettier-F7B93E?style=flat-square&logo=prettier&logoColor=black" alt="Prettier" />
<img src="https://img.shields.io/badge/Ruff-D7FF64?style=flat-square&logo=ruff&logoColor=black" alt="Ruff" />
</td>
</tr>
<tr>
<td valign="top"><b>Desktop & integrations</b></td>
<td>
<img src="https://img.shields.io/badge/Electron-47848F?style=flat-square&logo=electron&logoColor=white" alt="Electron" />
<img src="https://img.shields.io/badge/Qt_%2F_PySide6-41CD52?style=flat-square&logo=qt&logoColor=white" alt="Qt / PySide6" />
<img src="https://img.shields.io/badge/Selenium-43B02A?style=flat-square&logo=selenium&logoColor=white" alt="Selenium" />
<img src="https://img.shields.io/badge/Twilio-F22F46?style=flat-square&logo=twilio&logoColor=white" alt="Twilio" />
<img src="https://img.shields.io/badge/Nodemailer-22B573?style=flat-square" alt="Nodemailer" />
<img src="https://img.shields.io/badge/Supabase-3FCF8E?style=flat-square&logo=supabase&logoColor=white" alt="Supabase" />
<img src="https://img.shields.io/badge/Google_Sheets-34A853?style=flat-square&logo=googlesheets&logoColor=white" alt="Google Sheets" />
<img src="https://img.shields.io/badge/Apps_Script-4285F4?style=flat-square&logo=googleappsscript&logoColor=white" alt="Apps Script" />
</td>
</tr>
</table>

---

## By the numbers

<div align="center">

<img height="175" src="https://github-readme-stats.vercel.app/api?username=ax5hay&hide_rank=true&show_icons=true&hide_border=true&count_private=true&title_color=d8bd85&icon_color=8c2f24&text_color=c9c9c9&bg_color=0b0b0f" alt="GitHub stats" />
<img height="175" src="https://github-readme-stats.vercel.app/api/top-langs/?username=ax5hay&layout=compact&hide_border=true&langs_count=8&hide=jupyter%20notebook,html,css,scss,dockerfile,hcl,plpgsql,mako,go%20template,batchfile,makefile,cobol,roff&title_color=d8bd85&text_color=c9c9c9&bg_color=0b0b0f" alt="Most-used languages" />

</div>

<sub align="center">No rank grades, no vanity trophies: just what I build with and how much.</sub>

---

<div align="center">

<sub>Reliability is a feature. So is honesty about what isn't done yet.</sub><br/>
<sub><b>In thrust we trust.</b></sub>

</div>
