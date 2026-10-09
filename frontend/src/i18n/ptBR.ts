// Strings for the new "Canais" screens only (Phase 5 of docs/PROMPT_CANAIS.md).
// The rest of the dashboard stays in English for now — see that doc's
// section 8, item 3: switching the existing screens is a separate decision.
//
// Plain object + a tiny `t()` lookup helper, as the spec asks for. Components
// mostly read `pt.section.key` directly (type-checked); `t()` exists for the
// rare spot that needs a dynamic path.

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
    },
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
    statsMedian: (n: number) => `mediana de views: ${n.toLocaleString("pt-BR")}`,
    statsCount: (n: number) => `${n} vídeos`,
    outlierMultiplier: (n: number) => `${n.toFixed(1)}×`,
    pasteTranscript: "Colar transcrição",
    uploadTranscript: "Enviar .srt/.txt",
    transcriptSaved: "Transcrição salva",
    empty: {
      title: "Nenhuma referência ainda",
      hint: "Cole o link de um vídeo ou canal de referência acima para começar.",
    },
    noSearchProvider:
      "Cadastre um provedor YouTube Data API v3 em Providers antes de aprender uma referência.",
  },
  style: {
    learnedTitle: "O que o estúdio aprendeu",
    whyPrefix: "Por quê: ",
    confidenceLabels: { low: "confiança baixa", medium: "confiança média", high: "confiança alta" },
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
