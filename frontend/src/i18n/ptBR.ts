// Strings for the new "Canais" screens only (Phase 5 of docs/PROMPT_CANAIS.md).
// The rest of the dashboard stays in English for now — see that doc's
// section 8, item 3: switching the existing screens is a separate decision.
//
// Plain object + a tiny `t()` lookup helper, as the spec asks for. Components
// mostly read `pt.section.key` directly (type-checked); `t()` exists for the
// rare spot that needs a dynamic path.

/** "161031" -> "161 mil", "2500000" -> "2,5 mi" — avoids showing raw decimals
 * from an even-count median (e.g. "161.031,5") and matches how view counts
 * are normally written in pt-BR. */
export function formatCompactViews(n: number): string {
  const rounded = Math.round(n);
  if (rounded >= 1_000_000) return `${(rounded / 1_000_000).toFixed(1).replace(".", ",")} mi`;
  if (rounded >= 10_000) return `${Math.round(rounded / 1000)} mil`;
  if (rounded >= 1_000) return `${(rounded / 1000).toFixed(1).replace(".", ",")} mil`;
  return rounded.toLocaleString("pt-BR");
}

/** Human-readable age from an ISO timestamp, e.g. "há 12 dias". */
export function formatAge(publishedAt: string | null): string {
  if (!publishedAt) return "";
  const days = Math.floor((Date.now() - new Date(publishedAt).getTime()) / 86_400_000);
  if (days < 1) return "hoje";
  if (days < 30) return `há ${days} dia${days === 1 ? "" : "s"}`;
  if (days < 365) {
    const months = Math.round(days / 30);
    return `há ${months} ${months === 1 ? "mês" : "meses"}`;
  }
  const years = Math.round(days / 365);
  return `há ${years} ${years === 1 ? "ano" : "anos"}`;
}

export const pt = {
  nav: {
    canais: "Canais",
  },
  channels: {
    eyebrow: "Seus canais",
    title: "Canais",
    subtitle:
      "Cada canal guarda um padrão próprio: jeito do roteiro, voz, imagens, ritmo dos cortes. O estilo de um canal nunca vira o de outro.",
    newChannel: "+ Novo canal",
    newChannelFormTitle: "Novo canal",
    noStyleYet: "Sem estilo aprendido ainda",
    videosCount: (n: number) => `${n} ${n === 1 ? "vídeo" : "vídeos"}`,
    defaultVersion: (v: number) => `padrão v${v}`,
    lastVideo: (title: string) => `último: ${title}`,
    empty: {
      title: "Nenhum canal ainda",
      hint: "Crie um canal para aprender um estilo de referência e começar a gerar vídeos com ele.",
    },
  },
  channelDetail: {
    tabs: {
      referencias: "Referências",
      estilo: "Estilo",
      direcoes: "Direções",
      videos: "Vídeos",
      contas: "Contas",
    },
  },
  accounts: {
    hint: "Contas de publicação usadas para postar os vídeos deste canal. São compartilhadas entre todos os canais.",
    platform: "Plataforma",
    name: "Nome",
    socialIds: "IDs de conta no Post Bridge (separados por vírgula)",
    add: "Adicionar",
    empty: "Nenhuma conta ainda.",
    delete: "Excluir",
  },
  references: {
    boxTitle: "Aprender com vídeos e canais",
    boxHint:
      "Cole até 3 links do YouTube — de um vídeo específico ou de um canal inteiro. Leva de 2 a 5 minutos por vídeo; num canal, focamos nos vídeos que mais o representam.",
    principle:
      "O estilo é aprendido de forma abstrata — o conteúdo do outro canal nunca é copiado. Você confere tudo antes de usar.",
    placeholder: "Um link por linha (máx. 3)\nhttps://www.youtube.com/watch?v=...\nhttps://www.youtube.com/@algumcanal",
    submit: "Aprender estilo",
    submitting: "Enviando…",
    kindVideo: "Vídeo",
    kindChannel: "Canal",
    statusLabels: {
      pending: "na fila",
      fetching: "buscando dados",
      analyzing: "analisando estilo",
      ready: "pronto",
      failed: "falhou",
    },
    roleLabels: {
      top: "bombou",
      bottom: "abaixo da média",
      representative: "representativo",
      none: "",
    },
    statsMedian: (n: number) => `mediana de views: ${formatCompactViews(n)}`,
    statsCount: (n: number) => `${n} vídeos`,
    outlierMultiplier: (n: number) => `${n.toFixed(1)}×`,
    viewsPerDay: (n: number) => `${formatCompactViews(n)} views/dia`,
    transcriptSaved: "Transcrição automática pronta",
    deepdiveLabels: {
      none: "",
      pending: "na fila para análise",
      running: "analisando (transcrição + cenas)",
      ready: "análise pronta",
      failed: "análise falhou",
    },
    attentionNotesTitle: "Onde o público provavelmente ficou mais atento (estimativa)",
    attentionNotesHint: "Estimativa a partir de ritmo e estrutura — não é dado real de retenção.",
    sceneBreakdownTitle: "Cenas analisadas",
    empty: {
      title: "Nenhuma referência ainda",
      hint: "Cole o link de um vídeo ou canal de referência acima para começar.",
    },
    noSearchProvider:
      "Cadastre um provedor YouTube Data API v3 em Providers antes de aprender uma referência.",
  },
  production: {
    title: "Padrões de produção",
    hint: "Valem para todo vídeo deste canal, a menos que o vídeo em si defina algo diferente.",
    tone: "Tom",
    voice: "Voz",
    aspect: "Formato",
    aspectOptions: { "9:16": "9:16 vertical", "16:9": "16:9 horizontal" },
    subtitlesEnabled: "Legenda ligada por padrão",
    musicEnabled: "Música ligada por padrão",
    save: "Salvar padrões",
    saved: "Salvo ✓",
  },
  style: {
    learnedTitle: "O que o estúdio aprendeu",
    whyPrefix: "Por quê: ",
    confidenceLabels: { low: "confiança baixa", medium: "confiança média", high: "confiança alta" },
    missingData: "falta dado",
    missingDataHint: "Precisa de mais vídeos ou do arquivo de mídia para medir isso.",
    sendVideoToMeasure: "Enviar vídeo para medir",
    notReplicableTitle: "O que o estúdio ainda não faz igual",
    useOnChannel: "Usar neste canal",
    createChannelWithStyle: "Criar um canal com este estilo",
    versionHistory: "Histórico de versões",
    versionNote: "Vídeos já feitos não mudam — a nova versão vale só para os próximos.",
    draft: "rascunho",
    active: "ativo",
    archived: "arquivado",
    sections: {
      roteiro: "Roteiro",
      titulos: "Títulos",
      imagens: "Imagens",
      ritmo: "Ritmo dos cortes",
      legenda: "Legenda",
      musica: "Música e efeitos",
      voz: "Voz",
    },
    empty: {
      title: "Ainda sem estilo aprendido",
      hint: "Aprenda com um vídeo ou canal de referência na aba Referências para gerar o primeiro rascunho.",
    },
    noLlmProvider: "Cadastre um provedor de LLM em Providers para gerar o perfil de estilo.",
  },
  directions: {
    title: "Direções editoriais",
    subtitle: "Assuntos fortes com o motivo da oportunidade — nunca um vídeo para copiar.",
    directionLabel: (n: number) => `Direção ${String(n).padStart(2, "0")}`,
    approach: "Possível abordagem",
    source: "Fonte",
    use: "Usar esta direção",
    dismiss: "Descartar",
    discoverTitle: "Descobrir assuntos fortes",
    nichePlaceholder: "Ex.: curiosidades de ciência, finanças pessoais, histórias reais...",
    discoverSubmit: "Descobrir tendências",
    discoverHint: "Você recebe o assunto e o motivo da oportunidade, nunca um vídeo para copiar.",
    empty: {
      title: "Nenhuma direção ainda",
      hint: "Aprenda com um canal de referência ou descubra tendências para um nicho acima.",
    },
  },
  common: {
    cancel: "Cancelar",
    save: "Salvar",
    create: "Criar",
    loading: "Carregando…",
    notFound: "Não encontrado.",
    hide: "Ocultar",
  },
  create: {
    title: "Criar vídeo",
    subtitle: "Três passos: canal, como começar, e os ajustes deste vídeo.",
    step1Title: "Para qual canal é o vídeo?",
    noChannel: "Sem canal",
    newChannelChip: "+ Novo canal",
    channelHint: (name: string) =>
      `O vídeo sai com o jeito do canal ${name}: edição, legenda, imagens de fundo, música.`,
    step2Title: "Como você quer começar?",
    modes: {
      topic: { label: "Tenho um tema", hint: "Escreva o assunto e o estúdio escreve o roteiro." },
      discover: { label: "Descobrir assuntos fortes", hint: "O estúdio sugere temas com o motivo da oportunidade." },
      script: { label: "Já tenho o roteiro", hint: "Cole o texto; nenhuma palavra é alterada." },
      narration: { label: "Já tenho a narração", hint: "Em breve — envie o áudio e pule a etapa de voz." },
    },
    topicLabel: "Assunto / ideia",
    topicPlaceholder: "Ex.: Por que o oceano parece azul — fatos surpreendentes",
    discoverNicheLabel: "Nicho",
    discoverSubmit: "Descobrir tendências",
    discoverRule: "Você recebe o assunto e o motivo da oportunidade, nunca um vídeo para copiar.",
    scriptLabel: "Cole o roteiro inteiro",
    scriptRule:
      "Não muda uma palavra do seu texto: divide em partes, escolhe as imagens de cada parte. Instruções entre colchetes, como [imagem: ...], não são narradas.",
    narrationComingSoon: "Esse modo ainda não está disponível.",
    step3Title: "Ajustes deste vídeo",
    aiModel: "Modelo de IA",
    aiModelOptions: {
      fast: "Rápido",
      balanced: "Equilibrado",
      quality: "Qualidade",
      max: "Máximo",
    },
    duration: "Duração aproximada",
    durationPlaceholder: "Ex.: 45s, 20 min, 1 hora",
    durationHint: "Pode digitar qualquer duração — de segundos a horas.",
    language: "Língua do vídeo",
    languageLockedByChannel: "Travada pelo idioma do canal. Escolha \"Sem canal\" para um vídeo avulso.",
    backgroundMedia: "Imagens de fundo",
    backgroundMediaOptions: { video: "Só vídeos", mixed: "Vídeos e imagens" },
    videoImageRatio: "Proporção de vídeo vs. imagem",
    voiceSection: "Voz da narração",
    listen: "Ouvir",
    voiceFreeNote: "Voz grátis: nada é cobrado.",
    customizeSection: "Personalizar tese, público e tom",
    advancedSection: "Avançado",
    submit: "Gerar vídeo",
    submitting: "Iniciando…",
    missingProviders: "Sem provedor habilitado para:",
  },
  settings: {
    aiTitle: "Sua IA",
    aiHint:
      "Usar a assinatura do Claude Code ou do Codex instalados no seu computador — ainda não disponível. Falta confirmar os termos de uso do plano para uso programático e para distribuição a terceiros antes de implementar isso.",
    aiStatusPending: "Decisão pendente",
    voicesTitle: "Vozes",
    voicesFreeNote: "Microsoft Edge (grátis) está sempre disponível — nenhuma chave necessária.",
    voicesListen: "Ouvir",
    voicesFilterLanguage: "Idioma",
    voicesAll: "Todos",
    apiKeyPlaceholder: "Chave de API",
    saveAndTest: "Salvar e testar",
    removeKey: "Remover chave",
    configured: "configurado",
    testing: "Testando…",
    howToGetKey: "Como pegar a chave",
    mediaTitle: "Mídia",
    mediaFreeNote: "Sem chave necessária.",
    mediaNeedsKey: "Precisa de chave.",
  },
  lab: {
    title: "Laboratório de vídeo",
    hint: "Envie um vídeo seu para medir ritmo, legenda, paleta e estrutura — o estúdio nunca recria as cenas, só mede números e padrões.",
    uploadCta: "Enviar vídeo para medir",
    uploading: "Enviando…",
    dropHint: "Arraste um arquivo de vídeo aqui, ou clique para escolher",
    disclaimer:
      "Envie apenas vídeos que você tem direito de analisar. O sistema guarda números e padrões; o vídeo é apagado após a análise.",
    statusLabels: {
      pending: "na fila",
      running: "analisando",
      ready: "pronto",
      failed: "falhou",
    },
    scenesTitle: "Grade de cenas",
    rhythmTitle: "Linha do tempo de ritmo",
    beatLabels: {
      hook: "gancho",
      contexto: "contexto",
      escalada: "escalada",
      virada: "virada",
      fecho: "fecho",
      cliffhanger: "gancho final",
      cta: "chamada para ação",
    },
    fadeIcon: "fade",
    captionIcon: "legenda",
    remove: "Remover",
    removeConfirm: "Remover esta análise e todos os seus arquivos?",
    channelGrammarTitle: "Medido no Laboratório",
    measuredIn: (n: number) => `medido em ${n} ${n === 1 ? "vídeo" : "vídeos"}`,
    noChannelGrammar: "Nenhum vídeo medido neste canal ainda.",
    error: "Não foi possível analisar este vídeo.",
  },
  originality: {
    warningTitle: (pct: number) => `Roteiro ${pct}% parecido com uma referência aprendida`,
    warningHint: "Revise antes de aprovar — o estúdio nunca deveria copiar um vídeo específico.",
    variationTitle: "Parecido com outro vídeo recente deste canal",
    variationHint:
      "Reduz repetição superficial, mas não garante elegibilidade de monetização — isso depende do canal como um todo.",
  },
  scriptReview: {
    title: "Revisão do roteiro",
    otherTitles: "Outros títulos possíveis",
    hook: "GANCHO",
    close: "FECHO",
    showSpoken: "Mostrar como a voz vai ler (números por extenso)",
    approve: "Aprovar e gerar o vídeo",
    rewrite: "Escrever outro roteiro",
    changeRequest: "Mudar o pedido",
    costWarning: (cost: number) => `Isso vai gastar aproximadamente $${cost.toFixed(2)} em etapas pagas.`,
    confirmCost: "Confirmar e gerar mesmo assim",
    changeRequestTitle: "Mudar o pedido",
  },
  editor: {
    title: "Editor",
    backToVideo: "Voltar para o vídeo",
    undo: "Desfazer",
    redo: "Refazer",
    scenesTitle: (n: number) => `Cenas (${n})`,
    noScenesYet: "Este vídeo ainda não tem cenas para editar.",
    selectScene: "Selecione uma cena na linha do tempo.",
    narration: "Narração",
    duration: "Duração (s)",
    split: "Dividir cena",
    splitAt: "Dividir em",
    mergeNext: "Juntar com a próxima",
    lastSceneHint: "Esta é a última cena — não há com o que juntar.",
    saveScene: "Salvar cena",
    imageTitle: "Imagem da cena",
    imageRegenerate: "Gerar outra (IA)",
    imageSearch: "Buscar na internet",
    imageUpload: "Enviar do computador",
    searchPlaceholder: "Buscar fotos e vídeos…",
    searchButton: "Buscar",
    searchEmpty: "Nenhum resultado ainda.",
    alreadyUsed: "já usada",
    use: "Usar",
    captionTitle: "Legenda",
    captionEnabled: "Legenda ativada",
    captionSize: "Tamanho da fonte",
    captionColor: "Cor",
    captionPosition: "Posição",
    captionPositions: { top: "Topo", center: "Centro", bottom: "Rodapé" },
    saveCaption: "Salvar legenda",
    voiceTitle: "Voz",
    voiceRevoice: "Regerar narração com esta voz",
    exportTitle: "Exportar",
    exportButton: "Exportar vídeo",
    exporting: "Exportando…",
    download: "Baixar vídeo",
    notRenderedYet: "Ainda não renderizado.",
    savedHint: "Salvo — exporte de novo para atualizar o vídeo final.",
  },
};

/** Lookup a string by dotted path, e.g. `t("channels.newChannel")`. Prefer
 * reading `pt.section.key` directly where the shape is static (type-checked)
 * — this is for the rare case where the key itself is dynamic. */
export function t(path: string): string {
  const value = path.split(".").reduce<unknown>((node, key) => {
    if (node && typeof node === "object" && key in node) {
      return (node as Record<string, unknown>)[key];
    }
    return undefined;
  }, pt);
  return typeof value === "string" ? value : path;
}
