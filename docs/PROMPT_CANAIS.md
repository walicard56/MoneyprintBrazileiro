# PROMPT PARA O CLAUDE CODE — Aba "Canais" (aprender estilo por link), novas formas de começar um vídeo e editor

> Como usar: salve este arquivo no repositório (ex.: `docs/PROMPT_CANAIS.md`) e diga ao Claude Code:
> **"Leia docs/PROMPT_CANAIS.md inteiro. Execute somente a Fase 1 e pare para eu revisar."**
> Depois libere uma fase por vez. Não cole tudo e peça "faça tudo" de uma vez: o resultado piora e fica impossível de revisar.

---

## 0. Regras de trabalho (valem para todas as fases)

1. **Leia antes de escrever.** Antes de cada fase, leia os arquivos citados nela. Se algo que este prompt afirma não bater com o código, **o código vence**: avise-me e adapte.
2. **Uma fase por vez.** Ao terminar cada fase: rode `cd backend && pytest -q` e `ruff check .`; para o frontend, `cd frontend && npm run build`. Só então faça o commit da fase e pare com um relatório curto (formato na seção 9).
3. **Siga os padrões do repositório**, não os seus: providers síncronos com `@register`, schemas Pydantic em `app/schemas/`, routers em `app/api/routers/` com `dependencies=[AuthDep]`, migrations Alembic, componentes de `@/components/ui`, TanStack Query + `api.get/post` de `@/api/client`.
4. **Não toque em `MoneyPrinterV2/`.** Ele é a fonte original e deve ficar intacto.
5. **Nunca** coloque chaves de API em código, logs, testes ou commits. Chaves passam pelo pool de chaves já existente (`providers/keys.py`) e ficam criptografadas.
6. Python **3.12** (`>=3.12,<3.13`), `ruff` com `line-length = 100`, `from __future__ import annotations` no topo dos módulos novos.
7. Não adicione dependências pesadas ao núcleo da API. Se precisar de algo novo, coloque em extras do `pyproject.toml` e me avise.
8. Se uma decisão não estiver neste prompt e mudar o produto (não só o código), **pare e pergunte** (lista na seção 8).

---

## 1. Contexto do repositório (fatos já verificados)

O projeto é o **MoneyPrint**: backend FastAPI + Celery, frontend React/TS/Vite/Tailwind, evolução do MoneyPrinterV2.

**Backend (`backend/app/`)**
- `core/enums.py`: já existem `Capability.SEARCH` (sem nenhum provedor usando) e `AgentType.TREND` (sem agente implementado). Também `Stage`, `Status`, `RunMode`, `Platform`.
- `providers/base.py`: `BaseProvider`, `ProviderSpec`, `Usage`, `ProviderError` e as classes por capacidade (`LLMProvider`, `ImageProvider`, `TTSProvider`, `STTProvider`, `PublishProvider`). **Não existe `SearchProvider`.** Providers são **síncronos**.
- `providers/registry.py`: decorator `@register(display_name=..., default_endpoint=..., notes=..., param_schema=...)`; `discover()` importa automaticamente todos os módulos de `providers/impl/`.
- `providers/router.py`: `ProviderRouter(db).run(capability, fn, project_id=..., video_id=..., provider_config_id=...)`, com fallback por prioridade, pool de chaves, circuit breaker e custo. `fn(provider)` devolve `(valor, Usage)`. `.specs(capability)` lista os provedores.
- `providers/errors.py`: `ErrorCategory` (inclui `RATE_LIMIT`, `PERMISSION_ERROR`, `AUTH_ERROR`...) e `classify(status_code=, body=, exception=)`. Note: **HTTP 403 vira `PERMISSION_ERROR`**.
- `providers/impl/image_pexels.py`: bom modelo de provedor que consulta uma API HTTP com httpx, trata 429/`Retry-After` e baixa arquivo. `publish_postbridge.py` é o modelo de validação de chave + classificação de erro.
- `agents/base.py`: `AgentContext(db, video)` e `BaseAgent` (`complete()`, `render_prompt()`, `parse_json()` estático, `log()`). **`BaseAgent` exige um `Video`**; não serve direto para agentes que trabalham sobre um canal/referência.
- `agents/defaults.py`: `DEFAULT_AGENT_SETTINGS` e `DEFAULT_PROMPTS` (prompts em inglês com `{placeholders}`); `services/seeds.py::seed_defaults` é idempotente; `services/agent_config.py::resolve_agent_config(db, agent_type, project_id)` aceita `project_id=None`.
- `agents/base.py::AgentContext.base_fields()` usa `_SafeDict`: placeholders desconhecidos ficam intactos, então **adicionar placeholders novos não quebra prompts customizados existentes**.
- `agents/registry.py`: `STAGE_AGENTS` mapeia `Stage` → agente (RESEARCH, SCRIPT, REVIEW, STORYBOARD, CHARACTERS, SCENES, IMAGES, VIDEOS, VOICE, MUSIC, SUBTITLES, EDIT, QC, RENDER).
- `agents/content.py`: `ResearchAgent` hoje só pede notas ao LLM e grava em `video.config["research_notes"]`; `ScriptAgent` lê isso e grava `Script`.
- `orchestrator/engine.py`: `next_stage`, `step`, `run_pipeline_sync`, `approve_and_continue`; `DEFAULT_HYBRID_GATES = [SCRIPT, SCENES]`. `orchestrator/dispatch.py::start_pipeline` roda em modo `celery`, `thread` (padrão local) ou `sync` (testes), conforme `settings.execution_mode`. `orchestrator/tasks.py` tem `run_next_stage`.
- `db/models.py`: `Project` (é o "canal": nicho, idioma, estilo, `config` JSON), `Video` (`config` JSON, `stage_status` JSON), `Script` (`content`, `approved`), `Scene` (narração, duração, `image_path`, `clip_path`, `subtitle`...), `Job`, `Publication`, `CostRecord`, `Account`, etc. Mixins: `UUIDMixin`, `TimestampMixin`. Colunas enum usam `SAEnum`.
- `api/routers/videos.py`: `POST /projects/{id}/videos`, `/videos/batch`, `/videos/{id}/run`, `/approve`, `/cancel`, `GET/PATCH` de cenas, publish. `api/router.py` agrega os routers.
- `workers/celery_app.py` (beat_schedule) e `workers/schedule_tasks.py`.
- `engine/compose.py` e `engine/music.py`: montagem do vídeo (MoviePy). `agents/media.py` e `agents/finish.py`: imagens, voz, legendas, edição, QC, render.

**Migrations (Alembic)**
- Cadeia atual: `315ba935d928` → `7fe19fe78a4c` → `d95618696929` → `b9b512a5c9e6` → `d0fc2217bcf4`. **Confirme o head com `alembic heads`** antes de criar a nova revisão.
- Os enums foram criados como `sa.Enum('MAIÚSCULAS', name='agenttype')`: o banco guarda os **nomes** dos membros em maiúsculas. No **PostgreSQL** são enums nativos: adicionar um valor novo a `AgentType` exige `ALTER TYPE agenttype ADD VALUE IF NOT EXISTS 'NOME'` dentro de `with op.get_context().autocommit_block():`. No SQLite não é preciso nada. O `downgrade` desse passo pode ser no-op (Postgres não remove valores de enum) — documente isso no arquivo.

**Frontend (`frontend/src/`)**
- Rotas em `App.tsx`; menu lateral em `components/Layout.tsx` (array `NAV`); páginas atuais: Dashboard, Create, Projects, Videos, VideoDetail, Providers, Agents, Prompts, Accounts, Settings.
- `pages/Create.tsx` hoje é um formulário único (projeto, assunto, idioma, estrutura, tom, duração, voz, legenda).
- Tema escuro com Tailwind (`night`, `brand-*`, classes `glass` e `gradient-text`); primitivas em `@/components/ui` (`Button`, `Field`, `Input`, `PageHeader`, `Section`, `Select`, `Slider`, `Textarea`, `Toggle`, `EmptyState`); ícones em `@/components/icons`. A UI atual está em **inglês**.

**Testes (`backend/tests/`)**
- `conftest.py`: SQLite temporário, `MP_*` por variável de ambiente antes do import do app, fixture `client` (TestClient). `test_pexels.py` mostra o padrão de **fake do httpx** com payloads copiados da documentação oficial. `test_pipeline_e2e.py` mostra como o pipeline é testado ponta a ponta.

---

## 2. Objetivo do produto

Hoje o sistema gera roteiros do zero. Quero que ele **aprenda o estilo de canais de referência** e gere vídeos a partir desse estilo.

No dashboard, uma nova área **"Canais"**:
- Cada canal (= `Project` existente) tem um **perfil de estilo versionado** (jeito do roteiro, voz, imagens, ritmo, legenda, música).
- Dentro do canal, uma caixa **"Aprender com vídeos e canais"**: colo o link do YouTube e o sistema detecta sozinho:
  - **link de vídeo** → analisa só aquele vídeo;
  - **link de canal** → analisa o canal inteiro: puxa os vídeos, vê o que **bombou e o que não bombou** (views relativas à mediana do canal), e aprofunda nos que mais representam e nos outliers.
- Resultado 1: um **perfil de estilo** que eu reviso item por item antes de usar.
- Resultado 2: **"Direções editoriais"**: assuntos fortes com o *motivo da oportunidade* (ex.: "vídeo X teve 10,1× a mediana do canal"), **nunca um vídeo para copiar**.
- Na página do canal aparecem também **os vídeos que o meu sistema gerou** para ele (os `Video` do `Project`).
- No "Criar vídeo", em vez de um formulário único: escolher o canal → escolher **como começar** (Tenho um tema / Descobrir assuntos fortes / Já tenho o roteiro / Já tenho a narração) → ajustes.
- (Fase final, separada) um **editor** com linha do tempo por bloco do roteiro.

### Referência de UX (o que eu vi em vídeos de uma ferramenta similar)

Use como **inspiração de fluxo**, não copie textos, marca, identidade visual nem assets. Escreva a cópia da interface com palavras próprias e mantenha o tema escuro atual do repositório.

- Menu: **Criar · Canais · Meus vídeos · Importar · Configurações**.
- **Canais**: cartões coloridos por canal (selo de idioma, nome, nicho, "N vídeos · padrão vN · último: <título>", 3 a 4 bullets do estilo). Texto de apoio do tipo "cada canal guarda um padrão: jeito do roteiro, voz, imagens, ritmo dos cortes; o estilo de um canal não vira o de outro".
- **Aprender o estilo**: campo para colar link de vídeo ou canal (até 3 links), aviso de tempo ("leva de 2 a 5 minutos por vídeo; num canal, os 3 vídeos que mais o representam"), e a frase de princípio: o estilo é aprendido, **o conteúdo do outro canal nunca é copiado**. Mostra "Você confere antes de usar".
- **O que foi aprendido**: lista expansível "ver o que o estúdio aprendeu" com itens **com checkbox** (aceitar/recusar cada um) e um **"Por quê:"** com evidência numérica em cada item. Itens vistos: Roteiro, Linguagem, Imagens (inclui % de vídeo vs. imagem), Ritmo dos cortes, Legenda, Música e efeitos, Voz (grave/aguda, palavras por minuto). Fecha com **"O que o estúdio ainda não faz igual"** (lista honesta de limitações: apresentador na câmera, animação própria, mapa animado, texto animado na tela, transição de fusão).
- Ações do perfil: **"Usar no canal X"** (cria nova versão) e **"Criar um canal com este estilo"**.
- Versão do perfil: mudar o padrão **cria a versão 2**; **vídeos já feitos não mudam**, vale para todo vídeo novo.
- **Direções editoriais**: cartões numerados ("Direção 01"...), título, parágrafo com o motivo (views e múltiplo da mediana), "Possível abordagem", fonte com link e views, botões **"Usar esta direção"** e **"incluir abordagem"**.
- **Criar**, passo 1 "Para qual canal é o vídeo?" (chips: Sem canal / canais / + Novo canal; abaixo: "o vídeo sai com o jeito do canal X: edição, legenda, imagens de fundo, música").
- **Criar**, passo 2 "Como você quer começar?": 4 opções. Em "Descobrir assuntos fortes" há um campo de nicho (com exemplos clicáveis) e o botão "Descobrir tendências"; a frase "você recebe o assunto e o motivo da oportunidade, nunca um vídeo para copiar". Em "Já tenho o roteiro": caixa para colar o roteiro inteiro, com a regra "não muda uma palavra do seu texto: divide em partes, escolhe as imagens de cada parte; instruções entre colchetes, como `[imagem: ...]`, não são narradas".
- **Criar**, passo 3 "Ajustes deste vídeo": modelo de IA (rápido/equilibrado/qualidade/máximo), duração aproximada, língua do vídeo, imagens de fundo (só vídeos / vídeos e imagens), **proporção de vídeo vs. imagem** (slider, ex.: 40%), seção recolhível **"Voz da narração"** (serviço, voz, velocidade, botão "Ouvir", e a nota "voz grátis: nada é cobrado"), seção recolhível "Personalizar tese, público e tom".
- **Revisão do roteiro**: título, "outros títulos possíveis", capa (texto + imagem), seções com rótulos (GANCHO, FECHO), checkbox "mostrar como a voz vai ler (números por extenso)", e ações **"Aprovar e gerar o vídeo" / "Escrever outro roteiro" / "Mudar o pedido"**.
- **Custo**: a voz paga só é cobrada depois que eu confirmo o custo (na aprovação do roteiro ou na troca de voz).
- **Editor**: linha do tempo com blocos numerados (um por trecho do roteiro) com miniatura, forma de onda e legenda por bloco; painel lateral com abas **Plano / Legendas / Voz / Vídeo**; em cada bloco: "trocar por" (miniaturas sugeridas), **buscar na internet** (Wikimedia Commons, Openverse, NASA, Pexels, Pixabay; filtros "só fotos"/"só vídeos"; selo "já no vídeo" nas usadas), arrastar arquivo do computador, dividir bloco, deletar; legendas com fonte/cor/destaque/caixa-alta; voz por serviço (Microsoft grátis, ElevenLabs, Gemini) com voz padrão do vídeo; desfazer/refazer; "preparando o vídeo final em segundo plano (pode continuar editando)"; botão **Exportar vídeo**.
- **Configurações**: seção "Sua IA" (escolher o motor de texto e modelo padrão) e seção "Vozes" (grátis sempre ligadas; paga com chave, saldo/créditos restantes, "Salvar e testar", "Remover chave", "Como pegar a chave", custo mostrado antes de gastar).

---

## 3. Decisões de arquitetura (já tomadas — não reabra sem me avisar)

**D1 — "Canal" é o `Project`.** Não crie uma entidade `Channel` paralela. Nas telas novas o rótulo é "Canal"; a rota `/projects` continua funcionando.

**D2 — Perfil de estilo versionado e imutável.** Nova tabela `style_profiles`. Mudar o estilo cria uma **nova versão**; cada `Video` fixa `config["style_profile_id"]` na criação ("vídeos já feitos não mudam"). O perfil ativo do canal fica em `Project.config["active_style_profile_id"]`.

**D3 — Referências guardam metadados e a análise derivada, não conteúdo de terceiros.** Thumbnails: guardar só a URL (hotlink), não baixar. Transcrições: **não** devem aparecer na UI nem serem reproduzidas; ficam só o tempo necessário para análise (ver D5 e seção 6).

**D4 — Provedor de busca via `Capability.SEARCH`.** Criar `SearchProvider` em `providers/base.py` e o primeiro adaptador `providers/impl/search_youtube.py` (YouTube Data API v3, chave via pool de chaves). TikTok/outras plataformas ficam para depois, no mesmo padrão (ex.: adaptador Apify), **fora do escopo agora**.

**D5 — Transcrição é pluggable e honesta sobre limites.** A API oficial do YouTube **não entrega legendas de vídeos de outros criadores** (o download de legendas exige autorização do dono do vídeo). Portanto:
- Interface `TranscriptSource` em `services/transcripts.py` com adaptadores:
  1. `manual`: eu colo o texto ou envio `.srt`/`.txt` do vídeo de referência (sempre disponível);
  2. `stt`: eu envio um arquivo de áudio e ele passa pelo `STTProvider` já existente (`stt_whisper`/`stt_assemblyai`);
  3. `youtube_captions_unofficial`: **desligado por padrão** atrás de `MP_ENABLE_UNOFFICIAL_TRANSCRIPTS=false`, com aviso claro na documentação de que é não oficial, pode quebrar e pode violar os termos da plataforma. **Eu decido se ligo.**
- **Não implemente download de áudio/vídeo do YouTube** (yt-dlp e similares) nem scraping de HTML. Se parecer necessário, pare e pergunte.
- Sem transcrição, a análise **degrada com elegância**: usa só metadados (título, estatísticas, padrões de título, duração, cadência de postagem) e marca os campos de roteiro com `confidence: "low"`.
- Campos que dependem de mídia (ritmo dos cortes, música, volume relativo, altura da voz) **só são preenchidos se eu enviar o arquivo** (Fase 4b, opcional, com ffmpeg/ffprobe). Caso contrário ficam `null` com `why: "precisa do arquivo de mídia"`.

**D6 — Agentes de referência têm contexto próprio.** Não altere o construtor de `BaseAgent`/`AgentContext` (testes dependem). Crie `agents/reference.py` com `ReferenceAgentContext(db, project | None, source)` e uma base leve (`BaseServiceAgent`) que reutiliza `resolve_agent_config`, `ProviderRouter.run(..., project_id=..., video_id=None)` e `BaseAgent.parse_json`. Novos `AgentType`: `REFERENCE_ANALYST` (ficha por vídeo) e `STYLE_PROFILER` (agrega fichas em perfil). `AgentType.TREND` (já existe) gera as direções editoriais. Cada um com prompt padrão e configuração em `defaults.py` + `seeds.py` (editáveis na tela Prompts/Agents como os demais).

**D7 — Tudo que é demorado roda em segundo plano** pelo mesmo mecanismo de `orchestrator/dispatch.py` (celery/thread/sync) e o front acompanha por polling com `refetchInterval`, como já é feito no progresso do vídeo.

---

## 4. Fases

### FASE 1 — Fundação de dados (sem comportamento novo visível)

Leia: `db/models.py`, `db/base.py`, `core/enums.py`, `alembic/env.py`, a migration inicial (para ver como os enums foram declarados), `schemas/project.py`, `services/seeds.py`.

Entregue:
1. **Enums**: adicione `AgentType.REFERENCE_ANALYST` e `AgentType.STYLE_PROFILER`. Crie enums novos conforme necessário (`ReferenceKind`: `video|channel`; `ReferenceStatus`: `pending|fetching|analyzing|ready|failed`; `TranscriptStatus`: `none|manual|fetched|deleted`; `ProfileStatus`: `draft|active|archived`; `DirectionStatus`: `new|used|dismissed`). Siga a convenção do repo (`str, Enum`, coluna `SAEnum`).
2. **Modelos** em `db/models.py`:
   - `ReferenceSource`: `project_id` (nullable, FK `projects` `ondelete=SET NULL`; uma referência pode ser aprendida antes de existir canal), `url`, `kind`, `platform` (string, `"youtube"`), `external_id`, `title`, `owner_title`, `status`, `stage` (texto curto do passo atual), `progress` (0–100), `error`, `stats` JSON (n_videos, mediana de views, inscritos, janela de datas), `options` JSON.
   - `ReferenceVideo`: `source_id` (FK cascade), `external_id` (index, único por fonte), `title`, `published_at`, `duration_s`, `views`, `likes`, `comments`, `thumbnail_url`, `outlier_score` (float; views ÷ mediana do canal), `views_per_day`, `role` (`top|bottom|representative|none`), `analysis` JSON (ficha), `transcript_status`.
   - `StyleProfile`: `project_id` (FK cascade), `version` (int; único com `project_id`), `status`, `profile` JSON (schema na Fase 4), `source_ids` JSON, `notes`.
   - `EditorialDirection`: `project_id` (FK cascade), `source_id` (nullable), `title`, `why`, `approach`, `evidence` JSON (`video_external_id`, `views`, `multiplier`, `url`), `status`.
3. **Migration Alembic** nova, encadeada ao head real, criando as tabelas e **adicionando os valores novos de `agenttype` no Postgres** (ver seção 1: `autocommit_block`, nomes em MAIÚSCULAS). Teste `upgrade head` e `downgrade -1` em SQLite.
4. **Schemas Pydantic** em `schemas/reference.py` (Read/Create/Update por modelo; nenhum campo sensível).
5. Config: em `core/config.py` (leia antes) adicione `reference_max_videos` (padrão 200), `reference_deep_count` (padrão 5), `enable_unofficial_transcripts` (padrão `False`), `keep_transcripts` (padrão `False`), com as variáveis `MP_*` correspondentes documentadas em `backend/.env.example`.

Critérios de aceite: `pytest` e `ruff` verdes; `alembic upgrade head` e `downgrade -1` funcionam; teste novo cria e lê cada modelo; nenhum teste antigo alterado.

### FASE 2 — Provedor `SearchProvider` + YouTube

Leia: `providers/base.py`, `providers/registry.py`, `providers/impl/image_pexels.py`, `providers/impl/publish_postbridge.py`, `providers/errors.py`, `providers/router.py`, `tests/test_pexels.py`.

Entregue:
1. Em `providers/base.py`: dataclasses `SearchRequest(op, url="", external_id="", limit=200, page_token="")` e `SearchResponse(data, usage)`; classe abstrata `SearchProvider(BaseProvider)` com `capability = Capability.SEARCH` e `fetch(self, request) -> SearchResponse`. Operações (`op`): `"resolve"` (URL → tipo + id), `"video"` (detalhes de um vídeo), `"channel"` (dados do canal), `"channel_videos"` (lista paginada de uploads com estatísticas). Defina dataclasses tipadas de retorno (`ResolvedRef`, `ChannelInfo`, `VideoInfo`).
2. `providers/impl/search_youtube.py` com `@register(display_name="YouTube Data API v3", default_endpoint="https://www.googleapis.com/youtube/v3", notes=...)` e `provider_key = "youtube_data_api"`.
   - **Confira os endpoints e parâmetros na documentação oficial do YouTube Data API v3 antes de codar** e copie os formatos de payload nos testes, como `test_pexels.py` faz. Não confie na memória para nomes de parâmetros.
   - Estratégia de **cota baixa**: listar vídeos do canal pela playlist de uploads (`channels.list` → `contentDetails.relatedPlaylists.uploads` → `playlistItems.list` paginado) e buscar estatísticas em lote (`videos.list` com até 50 ids por chamada). **Evite `search.list`** (custa muito mais cota); só use como último recurso para URLs `/c/NomeCustom`, e documente isso.
   - Resolução de URL aceita: `youtube.com/watch?v=`, `youtu.be/`, `youtube.com/shorts/`, `youtube.com/@handle`, `youtube.com/channel/UC...`, `youtube.com/user/...`, `youtube.com/c/...`, com/sem `www.`/`m.`. Parser **puro** em `services/url_parse.py` (sem rede), com testes extensos.
   - **Anti-SSRF**: só aceite hosts de YouTube na allowlist; o servidor **nunca** faz GET em URL arbitrária enviada pelo usuário.
   - Erros: sem chave → `ProviderError(..., retryable=False)`; 403 com motivo de cota excedida → `category=ErrorCategory.RATE_LIMIT` com `retry_after` até o próximo reset diário de cota (confirme o horário na documentação) em vez do `PERMISSION_ERROR` padrão; 404/vídeo privado → `INVALID_REQUEST` com mensagem clara; use `classify()` para o resto. Nunca coloque a chave em mensagens de erro (chave vai em header/param, mas **sanitize** URLs antes de logar).
   - `health_check()` barato; `estimate_cost` fica em zero (a cota é o limite, não dinheiro); registre as unidades de cota usadas no `ProviderEvent` se isso for simples, senão deixe um TODO documentado.
3. A tela **Providers** já conhece a capacidade `search` (`api/types.ts` e a lista de capacidades em `pages/Providers.tsx`); só confirme que o catálogo mostra o novo provedor no formulário "Add provider" e que o teste de conexão funciona para ele. Atualize `backend/docs/providers.md`.

Testes: fake httpx no padrão de `test_pexels.py`; paginação de uploads; lotes de 50 ids; cota excedida; vídeo privado; todas as formas de URL.

Critérios de aceite: eu consigo cadastrar o provedor "YouTube Data API v3" na tela Providers, e um teste mostra `channel_videos` paginando e devolvendo estatísticas.

### FASE 3 — Ingestão de referências (vídeo ou canal) em segundo plano

Leia: `orchestrator/dispatch.py`, `orchestrator/tasks.py`, `workers/celery_app.py`, `services/costs.py`, `services/budget.py`, `services/logs.py`, `api/routers/projects.py`, `api/deps.py`.

Entregue:
1. `services/reference_ingest.py` com a função `ingest_reference(db, source_id)`:
   1. `parse_url` → `resolve` → decide `kind` (**vídeo = análise pontual; canal = varredura completa**);
   2. canal: busca até `reference_max_videos` uploads (mais recentes primeiro) com estatísticas; vídeo: busca só aquele;
   3. **estatísticas do canal**: mediana de views (ignore vídeos com menos de ~72 h para não distorcer), `views_per_day`, e `outlier_score = views / mediana`;
   4. **papéis**: `top` (maiores outliers, ex.: top 10% e `outlier_score >= 3`, limiares configuráveis), `bottom` (piores 10%, para contraste "o que bombou × o que não bombou"), `representative` (os `reference_deep_count` mais próximos do perfil típico do canal, que alimentam a análise profunda), `none`;
   5. atualiza `status`, `stage` e `progress` a cada passo; erros viram `status=failed` com `error` legível, **sem derrubar o worker**.
2. Despacho: `start_reference_ingest(source_id)` em `orchestrator/dispatch.py`, espelhando `start_pipeline` (celery/thread/sync) e uma task Celery correspondente em `orchestrator/tasks.py`.
3. Roteador `api/routers/references.py` (registrar em `api/router.py`):
   - `POST /references` — corpo `{urls: [..até 3..], project_id?: str}`; cria uma `ReferenceSource` por URL (detecção de tipo na hora), valida o host (allowlist), dispara a ingestão, devolve as fontes. Rejeite mais de 3 URLs e duplicatas já existentes no mesmo projeto.
   - `GET /references?project_id=` · `GET /references/{id}` (com `progress`) · `GET /references/{id}/videos?role=` · `DELETE /references/{id}`.
   - `POST /references/{id}/transcripts` (multipart, upload de `.srt`/`.txt`) e `POST /reference-videos/{id}/transcript` (texto colado) — só grava o status e entrega ao serviço de transcrição (Fase 4); **valide tamanho e tipo do arquivo**.
4. Sem chave/provedor `search` configurado, devolva **erro 409 acionável** ("cadastre o YouTube Data API em Providers"), não um 500.

Testes: ingestão de canal fake (mediana, outliers, papéis), ingestão de vídeo único, limites (3 URLs, duplicata), erro de cota vira `failed` com mensagem, modo `sync` no teste.

Critérios de aceite: colar um link de canal no `POST /references` cria a fonte, e `GET /references/{id}` mostra o progresso até `ready` com `stats` e vídeos classificados por papel.

### FASE 4 — Agentes: ficha por vídeo, perfil de estilo e direções editoriais

Leia: `agents/base.py`, `agents/content.py`, `agents/defaults.py`, `services/agent_config.py`, `services/seeds.py`, `providers/impl/stt_whisper.py`.

**Schema do perfil** (`schemas/reference.py::StyleProfileData`). Cada item tem `value`, `why` (evidência curta, com número quando houver), `confidence` (`low|medium|high`) e `accepted` (bool, padrão `True`; a UI deixa recusar por item):
```
roteiro:   narrador, tom, como_o_video_avanca, como_o_video_termina,
           linguagem, gancho_inicial, pergunta_que_prende
titulos:   padroes (lista de moldes abstratos, ex.: "número + adjetivo + tema + tipo de relato")
imagens:   tipo, percentual_video (0–100), fontes_sugeridas
ritmo:     corte_mediano_s (null se faltar mídia), palavras_por_minuto
legenda:   estilo (nenhuma|documental|palavra_a_palavra), cor, destaque, caixa_alta
musica:    genero, nivel_relativo_db (null se faltar mídia)
voz:       genero, timbre, velocidade, idioma, sugestao_de_voz
nao_replicavel: lista de strings ("apresentador na câmera", "animação própria", ...)
meta:      versao_do_schema, videos_analisados, tinha_transcricao (bool)
```

Entregue:
1. `services/transcripts.py` com a interface `TranscriptSource` e os adaptadores `manual` e `stt` (D5); o adaptador `youtube_captions_unofficial` existe mas **só carrega se `enable_unofficial_transcripts=True`**. Após a análise, **apague o texto da transcrição** (`transcript_status=deleted`) a menos que `keep_transcripts=True`.
2. `agents/reference.py`:
   - `ReferenceAnalystAgent`: por vídeo selecionado, recebe metadados + transcrição (se houver) e devolve uma **ficha JSON** abstrata (estrutura do roteiro, gancho, viradas, linguagem, ritmo). `json_mode=True`, validação Pydantic, **uma** nova tentativa com instrução de correção se o JSON falhar.
   - `StyleProfilerAgent`: agrega as fichas + estatísticas ("o que os `top` têm que os `bottom` não têm") em `StyleProfileData` rascunho (`status=draft`). Preenche `nao_replicavel` com o que o pipeline do MoneyPrint realmente não reproduz hoje.
   - `TrendAgent` (usa o `AgentType.TREND` existente): gera `EditorialDirection`s a partir dos `top`/outliers + nicho do canal. **Cada direção é um assunto e um ângulo originais, com o motivo da oportunidade (ex.: múltiplo da mediana); nunca reescreve um vídeo existente.**
   - **Regra anti-cópia nos prompts** (obrigatória): "Descreva o estilo de forma abstrata. Não reproduza frases, nomes próprios distintivos, bordões nem trechos do material de referência. Nenhuma citação literal."
3. Prompts padrão + `DEFAULT_AGENT_SETTINGS` em `agents/defaults.py` e `seeds.py` (idempotente) para `REFERENCE_ANALYST`, `STYLE_PROFILER` e `TREND`. Prompts em inglês, saída com os valores textuais no idioma do canal (`{language}`).
4. Integração na ingestão: depois de `ready` os metadados, se houver provedor LLM, rodar fichas → perfil rascunho → direções. Sem LLM: parar em `ready` sem perfil e avisar.
5. API (`api/routers/styles.py`): `GET /projects/{id}/style-profiles`; `GET /style-profiles/{id}`; `PATCH /style-profiles/{id}` (editar itens e `accepted`, só em `draft`); `POST /style-profiles/{id}/activate` (arquiva o ativo anterior, define `Project.config["active_style_profile_id"]`; **cria nova versão** se o perfil já era ativo e foi editado); `POST /style-profiles/{id}/create-channel` ("criar canal com este estilo": cria `Project` e ativa uma cópia v1); `GET /projects/{id}/directions`; `POST /directions/{id}/use` e `/dismiss`; `POST /projects/{id}/directions/discover` (gera tendências para um nicho digitado).
6. **Fase 4b (opcional, só se eu pedir)**: análise de mídia local com `ffprobe`/`ffmpeg` para preencher ritmo de cortes, volume relativo da música e timbre, quando eu enviar o arquivo.

Testes: schema do perfil (campos obrigatórios, limites), JSON inválido → 1 retry → falha limpa, ativação cria versão nova e arquiva a anterior, direções nunca contêm o título do vídeo-fonte copiado literalmente, degradação sem transcrição (`confidence=low`, `tinha_transcricao=false`).

Critérios de aceite: depois de ingerir um canal fake com LLM fake, existe um perfil `draft` com itens `accepted`, direções com `evidence.multiplier`, e ativar o perfil muda `Project.config`.

### FASE 5 — Frontend: aba "Canais"

Leia: `App.tsx`, `Layout.tsx`, `pages/Projects.tsx`, `pages/Create.tsx`, `pages/VideoDetail.tsx`, `components/ui.tsx`, `components/icons.tsx`, `api/client.ts`, `api/types.ts`, `index.css`/config do Tailwind.

Decisão de idioma: **as telas novas ficam em pt-BR**, com as strings em `frontend/src/i18n/ptBR.ts` (objeto simples + helper `t()`), sem trocar as telas antigas. (Registre no relatório que a UI ficou mista; posso pedir i18n completo depois.)

Entregue:
1. Rotas `canais` e `canais/:id` em `App.tsx`; item "Canais" no `NAV` de `Layout.tsx` (ícone novo em `icons.tsx` se necessário).
2. `pages/Channels.tsx`: grade de cartões (um por `Project`), cor derivada de um hash do nome, selo de idioma, nicho, "N vídeos · padrão vN", bullets do perfil ativo (ou "sem estilo aprendido ainda"), botão "+ Novo canal" (reaproveite a criação de `Project`).
3. `pages/ChannelDetail.tsx` com abas **Referências · Estilo · Direções · Vídeos**:
   - **Referências**: caixa "Aprender com vídeos e canais" (textarea, uma URL por linha, máx. 3, mostra o aviso de tempo e a frase de que o conteúdo nunca é copiado); lista das fontes com **barra de progresso** por polling (`refetchInterval` ~2 s enquanto `status` não for final); por fonte, tipo detectado (vídeo/canal), estatísticas do canal e uma tabela de vídeos com `outlier_score`, rótulos "bombou / abaixo da média" e miniatura (hotlink); ação "colar transcrição" / "enviar .srt" por vídeo.
   - **Estilo**: "o que o estúdio aprendeu" com checkbox por item e o "Por quê:"; bloco "O que o estúdio ainda não faz igual"; badge de confiança; botões **"Usar neste canal"** (ativa → nova versão) e **"Criar um canal com este estilo"**; histórico de versões (somente leitura) com a nota "vídeos já feitos não mudam".
   - **Direções**: cartões "Direção 01…" com título, motivo, "Possível abordagem", fonte com views e botões "Usar esta direção" (leva ao Criar com o tema preenchido) e "Descartar".
   - **Vídeos**: lista dos `Video` do projeto (reaproveite o componente/consulta de `pages/Videos.tsx`).
4. Estados vazios e de erro acionáveis (sem provedor `search`, sem LLM, cota excedida), nunca uma tela em branco.
5. Mantenha o tema escuro e os componentes existentes; **não copie** visual de produtos de terceiros.

Critérios de aceite: `npm run build` limpo; com a API rodando consigo colar um link, ver o progresso, revisar o perfil com checkboxes, ativá-lo e ver "padrão v2" no cartão do canal.

### FASE 6 — Integração com o pipeline + novas formas de começar

Leia: `agents/base.py`, `agents/content.py`, `agents/visual.py` (StoryboardAgent), `agents/media.py`, `agents/finish.py`, `orchestrator/engine.py`, `api/routers/videos.py`, `schemas/video.py`, `services/costs.py`, `services/budget.py`, `tests/test_pipeline_e2e.py`.

Entregue:
1. **Estilo no pipeline**: em `AgentContext.base_fields()` adicione `style_guidance` (texto compilado só dos itens `accepted` do perfil fixado em `video.config["style_profile_id"]`; vazio se não houver) e injete `{style_guidance}` nos prompts padrão de script, revisor e storyboard em `defaults.py`. Ao criar o vídeo (`create_video`/`batch`), fixe o `style_profile_id` ativo do projeto e aplique os defaults derivados (`structure`, `tone`, voz, legendas, proporção de vídeo vs. imagem) **sem sobrescrever o que o usuário definiu explicitamente**. `ResearchAgent`: se houver `direction_id`, use o motivo da oportunidade e a abordagem como notas de pesquisa.
2. **Modos de entrada** via `config["entry_mode"]` ∈ `topic | discover | script | narration`, aplicados por `engine.apply_entry_mode(video)` na criação:
   - `topic`: comportamento atual.
   - `discover`: fluxo da UI usa `POST /projects/{id}/directions/discover`, e a direção escolhida vira `topic` + `config["direction_id"]` + `config["opportunity_reason"]`; depois segue como `topic`.
   - `script`: grava `Script(content=<texto do usuário>, approved=True)`, marca RESEARCH/SCRIPT/REVIEW como concluídos com `config["skipped_stages"]` e log "pulado: roteiro fornecido", e liga `config["script_locked"]=True`. **Não pode alterar uma palavra do texto.** Instruções entre colchetes (`[imagem: ...]`, `[image: ...]`) e entre parênteses de direção saem da narração e viram dicas em `Scene.visual_description`. O `StoryboardAgent`, com `script_locked`, divide o texto em cenas **sem reescrever**: valide que a concatenação das narrações das cenas é igual ao texto original (ignorando espaços); se o LLM alterar, use um **divisor determinístico por frases** como fallback.
   - `narration` (**sub-fase 6b, só depois do `script`**): upload de áudio → `STTProvider` gera SRT com tempos → cenas nascem dos trechos e a duração vem do áudio; pula VOICE.
3. **Revisão do roteiro**: endpoints `POST /videos/{id}/regenerate-script` ("escrever outro roteiro", mantém tema/estilo) e `PATCH` do pedido ("mudar o pedido": tema, tom, duração) que reabre a etapa de roteiro. O gate padrão do modo `hybrid` já para após `SCRIPT`; reaproveite.
4. **Confirmação de custo**: leia `services/costs.py` e `budget.py` e reaproveite o que existir; se não houver, crie `GET /videos/{id}/estimate` somando o custo estimado das etapas pagas restantes (voz paga, imagens) a partir do `cost_config` dos provedores. Em `/approve`, se o custo estimado for > 0 e o modo não for `auto`, exija `confirm_cost: true`; provedores gratuitos nunca pedem confirmação.
5. **Frontend `pages/Create.tsx`**: transforme em assistente de 3 passos (canal → como começar → ajustes), em pt-BR, mantendo o formulário atual como seção "Avançado" para não perder nada. Passo 2 com os 4 modos (campos específicos de cada um). Passo 3 com modelo/provedor de IA, duração, idioma, proporção vídeo × imagem, voz (com "Ouvir" e a nota de custo) e "Personalizar tese, público e tom". Na revisão do roteiro (em `VideoDetail.tsx`), botões **Aprovar e gerar / Escrever outro roteiro / Mudar o pedido**, título com alternativas e o aviso de custo antes de confirmar.

Testes: `style_guidance` aparece no prompt renderizado e some sem perfil; `script_locked` preserva o texto byte a byte (e o fallback determinístico entra quando o LLM falso reescreve); estágios pulados refletem em `/progress`; vídeo antigo não muda ao ativar uma versão nova do perfil; `/approve` exige `confirm_cost` só quando há custo.

Critérios de aceite: criar um vídeo no modo `script` com colchetes gera cenas cujo texto concatenado é idêntico ao colado, e o mesmo vídeo no modo `topic` usa o `style_guidance` do canal.

### FASE 7 — Editor (SEPARADA: só comece depois que eu aprovar a Fase 6)

Leia: `agents/finish.py`, `agents/media.py`, `engine/compose.py`, `engine/music.py`, `providers/impl/image_*.py`, `providers/impl/tts_*.py`, `api/routers/videos.py` (cenas), `schemas/video.py`.

Escopo: editor na página do vídeo, usando os `Scene` como blocos.
1. **Linha do tempo** com um bloco por `Scene` (miniatura, duração, texto da legenda, forma de onda se houver áudio). Selecionar, reordenar (se fizer sentido para o roteiro), **dividir** e **mesclar** blocos (`POST /videos/{id}/scenes/split|merge`), apagar.
2. **Trocar mídia** de um bloco: sugestões automáticas, **busca** (`GET /media/search?q=&kind=photo|video&source=`) e upload do computador. Novos provedores de mídia livres no mesmo padrão do Pexels (`providers/impl/image_*.py`): Wikimedia Commons, Openverse, NASA e Pixabay. **Licença e atribuição são obrigatórias**: adicione `media_meta` JSON em `Scene` (migration) com `source`, `license`, `author`, `url`; gere uma lista de créditos para a descrição da publicação quando a licença exigir. Marque "já no vídeo" nos itens usados.
3. **Painel lateral** com abas Plano · Legendas · Voz · Vídeo: legendas (fonte, cor, destaque, caixa-alta, posição, tamanho) no nível do vídeo e por bloco; voz por bloco ou do vídeo inteiro (serviço/voz/velocidade, "Ouvir", nota de custo).
4. **Desfazer/Refazer** com tabela `edit_operations` (`video_id`, `seq`, `op`, `payload`, `inverse`).
5. **Re-render em segundo plano**: reexecutar só as etapas necessárias (leia `agents/finish.py`/`engine/compose.py`), com progresso e sem bloquear a edição; botão **Exportar vídeo** só habilita quando o render termina.
6. Reaproveite `GET/PATCH /scenes` já existentes; documente os endpoints novos no README.

Antes de codar: **apresente um plano curto da Fase 7 e espere meu "ok"**, porque ela mexe no motor de render e é a parte de maior risco.

---

## 5. Convenções de código (resumo)

- Providers: síncronos, `@register`, erros via `ProviderError` + `classify`, nunca logar chave, `httpx.Client(timeout=...)`.
- Rotas: `APIRouter(tags=[...], dependencies=[AuthDep])`, `get_db`, 404/409/400 com mensagens em inglês claras (a UI traduz).
- Migrations: uma revisão por fase com banco novo, `downgrade` honesto (ou documentado como no-op quando o banco não permite).
- Prompts: em inglês, com placeholders `{...}`, editáveis pelas telas Prompts/Agents; nada de prompt fixo dentro do agente.
- Front: componentes pequenos, estado de servidor no TanStack Query, polling só enquanto necessário, estados de carregamento/erro/vazio em toda tela.

## 6. Segurança, legal e custo (inegociável)

- **Estilo, não cópia.** O sistema aprende padrões abstratos. Nada de reproduzir roteiros, frases, bordões, nomes distintivos ou assets de terceiros; a UI mostra a regra e os prompts a impõem.
- **Sem scraping de HTML e sem download de mídia do YouTube.** Só API oficial e arquivos que **eu** envio. Transcrição não oficial atrás de flag desligada.
- **Termos de uso:** registre em `backend/docs/` uma nota curta sobre limites da API oficial (cota diária, sem legendas de terceiros) e sobre os riscos da transcrição não oficial. TikTok/outras plataformas ficam para depois, com API oficial ou provedor de terceiro.
- **Dados de terceiros:** guardar só metadados públicos e a análise derivada; thumbnails por URL; transcrições apagadas após a análise por padrão (`MP_KEEP_TRANSCRIPTS=false`).
- **Entradas do usuário:** allowlist de hosts, limite de 3 URLs por envio, validação de tamanho e tipo de upload, sem leitura de URL arbitrária no servidor, sanitização de qualquer texto que volte para a UI.
- **Custo:** a cota do YouTube é o limite da coleta (use a playlist de uploads, evite `search.list`); LLM e voz passam pelo `ProviderRouter` e entram em `CostRecord`/`budget`; nada pago roda sem a confirmação de custo da Fase 6.

## 7. Testes e qualidade

- Cada fase adiciona testes **no mesmo estilo** dos existentes (`tests/`, fixtures de `conftest.py`, fakes de httpx como em `test_pexels.py`, pipeline como em `test_pipeline_e2e.py`).
- Cobertura mínima por fase: caminho feliz, erro de provedor, entrada inválida, e uma regressão que prove que o comportamento antigo não mudou.
- Antes de encerrar a fase: `pytest -q`, `ruff check .`, `npm run build`, e um `alembic upgrade head` em banco limpo.
- Se um teste antigo quebrar, **não o edite para passar**: explique por quê e peça decisão.

## 8. Pare e pergunte antes de decidir sozinho

1. Ligar ou não a transcrição não oficial do YouTube (`MP_ENABLE_UNOFFICIAL_TRANSCRIPTS`).
2. Qualquer download de mídia do YouTube, scraping de HTML ou uso de `yt-dlp`.
3. Trocar o idioma das telas existentes (hoje em inglês) para pt-BR.
4. Vídeos longos (20 min a 1 h) e formato 16:9 como padrão: o pipeline atual é pensado para curtos (slider de duração 10–90 s, 9:16). **Não ampliar nesta rodada**; só avise onde o código assume curto.
5. Mudanças no motor de render (`engine/compose.py`) na Fase 7.
6. Adicionar dependências novas ao núcleo.

## 9. Formato do relatório ao fim de cada fase

1. O que foi feito (3–6 linhas) e quais arquivos mudaram.
2. Como rodar e testar (comandos exatos).
3. Resultado de `pytest`, `ruff` e `npm run build`.
4. O que **não** foi feito ou ficou com TODO, e por quê.
5. Decisões que precisam de mim (seção 8) e a sugestão do que fazer na próxima fase.
