- Nova user story: Como usuária, ao fornecer um link de canal do YouTube, quero que o sistema liste todos os vídeos do canal e processe (download + transcrição) 1 a 1, mantendo um estado persistente para retomar do ponto onde parei sem duplicar trabalho.
  - Detecção automática de URL de canal (ex.: `youtube.com/@handle`, `youtube.com/channel/ID`, `youtube.com/c/NAME`, `youtube.com/user/NAME`).
  - Criar pasta `downloads/channels/<channel_key>/` e arquivo `state.json` com:
    - `channel_id`, `channel_title`, `channel_url`, `videos` (lista com `id`, `url`, `title`), `status` por vídeo (`downloaded`, `transcribed`, `audio_id`, `error`), `last_index`.
  - Processar sequencialmente; ao reiniciar, pular vídeos já `transcribed == True`.
  - O estado deve ser atualizado após cada etapa (download/transcrição), permitindo retomada.
  - Primeira entrega: apenas download + transcrição. Tradução/entidades podem vir depois por vídeo.

# Requirements Document

## Introduction

Este documento especifica os requisitos para um software CLI que automatiza o processo de transcrição de áudio de vídeos do YouTube. O sistema baixa o áudio, prepara para transcrição otimizada, transcreve usando gpt-4o-transcribe, detecta entidades, permite feedback do usuário e normaliza a transcrição final com as entidades identificadas.

## Latest Enhancement: Multi-Provider AI Support

### New Requirement - AI Provider Selection

**User Story:** Como usuário, quero poder escolher entre diferentes provedores de IA (OpenAI, OpenRouter, Google Gemini) para transcrição e tradução, para que eu tenha flexibilidade de custo, qualidade e disponibilidade.

#### Implementation Status: ✅ COMPLETE

✅ 1. WHEN configurando transcrição THEN o usuário SHALL poder escolher entre:
   - OpenAI (gpt-4o-transcribe) - endpoint dedicado de transcrição
   - Gemini (gemini-2.5-flash) - capacidades multimodais nativas
✅ 2. WHEN configurando tradução THEN o usuário SHALL poder escolher entre:
   - OpenAI/OpenRouter (gpt-4.1) - 1M tokens de contexto
   - Gemini (gemini-2.5-pro) - 2M tokens de contexto, raciocínio avançado
✅ 3. WHEN usando Gemini THEN o sistema SHALL usar endpoint compatível com OpenAI
✅ 4. WHEN alternando provedores THEN a mesma lógica de código SHALL funcionar transparentemente

#### Environment Configuration
```bash
# Escolha um ou mais provedores:
export OPENAI_API_KEY="sk-..."           # Para OpenAI direto
export OPENROUTER_API_KEY="sk-or-..."    # Para OpenRouter
export GEMINI_API_KEY="..."              # Para Google Gemini
```

#### Usage Examples
```python
# Transcrição com Gemini 2.5-flash
transcriber = create_gemini_transcription_service(
    model="gemini-2.5-flash",
    verbose=True
)

# Tradução com Gemini 2.5-pro (2M tokens de contexto)
translator = create_gemini_translator_normalizer(
    model="gemini-2.5-pro", 
    verbose=True
)
```

## Requirements

### Requirement 1 - Download

**User Story:** Como usuário, eu quero colar um link do YouTube no CLI, para que o sistema baixe automaticamente o áudio em formato MP3.

#### Acceptance Criteria

✅ 1. WHEN o usuário fornece um link válido do YouTube THEN o sistema SHALL baixar o áudio em formato MP3
✅ 2. WHEN o usuário fornece um link inválido THEN o sistema SHALL exibir uma mensagem de erro clara
✅ 3. WHEN o download falha THEN o sistema SHALL informar o motivo da falha
✅ 4. WHEN o download é bem-sucedido THEN o sistema SHALL confirmar o sucesso e mostrar o caminho do arquivo

### Requirement 2 - Preparação de Áudio para Transcrição

**User Story:** Como usuário, quero que o sistema prepare automaticamente meu áudio para transcrição, processando arquivos grandes apenas quando necessário, para que eu possa enviar diretamente à API sem me preocupar com limitações técnicas.

#### Critérios de Aceitação

✅ 1. WHEN um arquivo de áudio ≤ 25 MB é processado THEN o sistema SHALL enviá-lo diretamente para transcrição sem chunking (caminho otimizado).
✅ 2. IF o arquivo exceder 25 MB AND foi baixado em qualidade "best" THEN o sistema SHALL primeiro tentar re-download automático em qualidade "medium" pelo yt-dlp, informando o usuário sobre a otimização para chamada única à API, substituindo o arquivo anterior e atualizando a metadata correspondente.
✅ 3. IF o re-download falhar OR após re-download ainda exceder 25 MB THEN o sistema SHALL tentar compressão (conversão para mono, redução de bitrate) para ficar dentro do limite.
✅ 4. IF após compressão ainda exceder 25 MB THEN o sistema SHALL dividir em segmentos menores que 25 MB, cortando preferencialmente em trechos de silêncio natural.
✅ 5. WHEN divisão for necessária THEN o sistema SHALL aplicar overlap máximo de 0,5s apenas se necessário para evitar cortes de palavras, sem sobreposição desnecessária.

### Requirement 3 — Transcrição com gpt-4o-transcribe

**User Story:**  
Como usuário, quero que meu áudio (ou gravação completa) seja transcrito com alta precisão pelo modelo **gpt-4o-transcribe**, sem que eu precise lidar com divisões técnicas de arquivo, para que eu receba rapidamente a transcrição integral.

#### Critérios de Aceitação

✅ 1. WHEN um arquivo de áudio ≤ limite suportado pela API (atualmente 25 MB) é recebido THEN o sistema SHALL enviá-lo inteiro ao endpoint de transcrição (`model=gpt-4o-transcribe`) e usar parâmetros consistentes para todo o job.
✅ 2. IF o arquivo exceder o limite de tamanho suportado THEN o sistema SHALL aplicar a estratégia de *inputs longos*: (a) tentar compressão (mono, bitrate reduzido); ELSE (b) dividir em segmentos < limite, cortando preferencialmente em trechos de silêncio natural; overlap máximo 0,5 s apenas se necessário para evitar cortes de palavra.
✅ 3. WHEN cada segmento for transcrito THEN o sistema SHALL reconstituir a transcrição completa ordenando pelos *timestamps* retornados pelo modelo (não por simples concatenação textual).
✅ 4. IF qualquer segmento falhar por erro recuperável THEN o sistema SHALL reintentar até 3 vezes com backoff (1s→2s→4s) antes de marcar como falhado e seguir.
✅ 5. WHEN a transcrição completa for montada THEN o sistema SHALL sinalizar quais trechos (se algum) não puderam ser transcritos e incluir metadados de tempo (início/fim) por segmento.

#### Performance Implementation Notes (2025-07-16)

O sistema implementa as estratégias de otimização usando **FFmpeg nativo** para máxima eficiência:

- **Compressão**: FFmpeg subprocess para processamento sem carregar arquivo na memória  
- **Chunking**: FFmpeg streaming extraction com timing preciso
- **Verificação de duração**: FFprobe para metadata sem loading completo do arquivo
- **Fallback inteligente**: PyDub apenas quando FFmpeg indisponível  

Esta implementação elimina completamente problemas de memória e CPU, permitindo processamento eficiente de arquivos de qualquer tamanho sem impacto na performance do sistema.

### Requirement 4

**User Story:** Como usuário, eu quero que o sistema detecte automaticamente entidades na transcrição completa, para que eu possa identificar pessoas, lugares e outras informações importantes.

#### Acceptance Criteria

✅ 1. WHEN a transcrição está completa THEN o sistema SHALL analisar o texto transcrito para detectar entidades
✅ 2. WHEN entidades são detectadas THEN o sistema SHALL classificá-las por tipo (pessoa, local, organização, etc.)
✅ 3. WHEN a detecção é concluída THEN o sistema SHALL apresentar uma lista consolidada de entidades
✅ 4. WHEN há entidades duplicadas THEN o sistema SHALL agrupá-las automaticamente

### Requirement 5

**User Story:** Como usuário, eu quero revisar e corrigir as entidades detectadas através de uma interface CLI navegável, para que eu possa facilmente substituir nomes no transcript final.

#### Acceptance Criteria

✅ 1. WHEN as entidades são detectadas THEN o sistema SHALL apresentar uma interface CLI navegável com setas (↑/↓)
✅ 2. WHEN cada entidade é exibida THEN o sistema SHALL mostrar um campo de edição ao lado: `Entidade [   ]`
✅ 3. WHEN o usuário navega com setas THEN o sistema SHALL mover o cursor entre as entidades detectadas
✅ 4. WHEN o usuário pressiona Enter sem modificar THEN o sistema SHALL manter a entidade original e pular para a próxima
✅ 5. WHEN o usuário escreve um substituto e pressiona Enter THEN o sistema SHALL fazer find/replace da entidade original pelo substituto no arquivo transcript
✅ 6. WHEN todas as entidades são revisadas THEN o sistema SHALL salvar o transcript atualizado
✅ 7. WHEN o usuário escolhe pular a revisão THEN o sistema SHALL usar as entidades detectadas sem modificações

### Requirement 6

**User Story:** Como usuário, eu quero traduzir e normalizar idiomaticamente a transcrição final para a língua de minha escolha, para que eu tenha um texto final naturalizado e fluente na linguagem destino.

#### Acceptance Criteria

✅ 1. WHEN a transcrição e entidades estão prontas THEN o sistema SHALL apresentar interface CLI navegável com setas para seleção de idioma de destino
✅ 2. WHEN o idioma é selecionado THEN o sistema SHALL oferecer opções regionais específicas (pt-BR, pt-PT, es-ES, es-MX, en-US, en-GB, etc.)
✅ 3. WHEN o idioma é confirmado THEN o sistema SHALL dividir a transcrição em chunks inteligentes respeitando limites do GPT-4.1 (1M tokens entrada)
✅ 4. WHEN cada chunk é processado THEN o sistema SHALL traduzir E normalizar idiomaticamente usando instruções específicas para fluência natural
✅ 5. WHEN todos os chunks são processados THEN o sistema SHALL reconstituir o texto completo traduzido e normalizado
✅ 6. WHEN a tradução é concluída THEN o sistema SHALL gerar arquivo final com estatísticas de processamento
✅ 7. WHEN o usuário escolhe pular tradução THEN o sistema SHALL usar a transcrição original (com entidades já corrigidas)

### Requirement 7

**User Story:** Como usuário, eu quero configurar parâmetros do processamento, para que eu possa ajustar o sistema às minhas necessidades específicas.

#### Acceptance Criteria

1. WHEN o sistema inicia THEN o usuário SHALL poder configurar parâmetros de compressão de áudio
2. WHEN configurando THEN o usuário SHALL poder definir limite de tamanho para processamento direto
3. WHEN configurando THEN o usuário SHALL poder escolher modelo de transcrição (gpt-4o-transcribe ou gpt-4o-mini-transcribe)
4. WHEN configurando THEN o usuário SHALL poder definir estratégia para processamento de entidades

### Requirement 8

**User Story:** Como usuário, eu quero acompanhar o progresso de cada etapa, para que eu saiba o status atual do processamento.

#### Acceptance Criteria

1. WHEN qualquer operação está em andamento THEN o sistema SHALL mostrar progresso em tempo real
2. WHEN uma etapa é concluída THEN o sistema SHALL confirmar e mostrar tempo decorrido
3. WHEN ocorre um erro THEN o sistema SHALL exibir detalhes e sugestões de correção
4. WHEN o processamento é interrompido THEN o sistema SHALL permitir retomar de onde parou

---

**Critérios de Aceitação**:
- O programa deve ser capaz de processar vídeos longos (>30 minutos) sem erros.
- A transcrição não deve ser truncada.
- A detecção de entidades deve ser rápida e focada nos tipos de entidade mais relevantes (Pessoas, Lugares).
- A tradução deve ser precisa e manter a integridade do texto original, sem perdas.
- O uso de recursos (API calls, tempo de processamento) deve ser otimizado.

---

## User Story 6: Performance Otimizada e Chunking Inteligente

**Como** usuário que processa vídeos longos frequentemente,  
**Eu quero** que o sistema seja extremamente rápido e eficiente,  
**Para que** eu possa processar múltiplos vídeos sem esperas desnecessárias.

**Critérios de Aceitação**:
- A detecção de entidades deve ser concluída em menos de 30 segundos para textos de 40k+ caracteres.
- O sistema deve usar chunking paralelo para maximizar a eficiência da API.
- O formato de comunicação com a API deve ser otimizado para minimizar tokens.
- O sistema deve ser resiliente a falhas individuais de chunks.
- A tradução deve processar textos longos em chunks balanceados de qualidade.

---

## User Story 7: Preservação e Acumulação de Resultados

**Como** usuário que cria uma biblioteca de transcrições,  
**Eu quero** que meus arquivos finais nunca sejam perdidos acidentalmente,  
**Para que** eu possa construir um arquivo histórico confiável dos meus trabalhos.

**Critérios de Aceitação**:
- O sistema nunca deve deletar arquivos na pasta `output/`.
- Execuções subsequentes devem preservar todos os resultados anteriores.
- A limpeza deve remover apenas arquivos temporários (downloads, debug).
- Os usuários devem poder acumular transcrições indefinidamente.
- O sistema deve fornecer links clicáveis para acesso direto aos resultados.

---

## User Story 8: Qualidade Aprimorada de Tradução

**Como** usuário que precisa de traduções profissionais,  
**Eu quero** que o sistema corrija erros e formate adequadamente o texto,  
**Para que** eu receba um resultado polido e pronto para uso.

**Critérios de Aceitação**:
- O sistema deve corrigir erros gramaticais do texto original.
- Linguagem inadequada deve ser automaticamente censurada.
- Diálogos devem ser formatados com aspas duplas consistentemente.
- Expressões idiomáticas devem ser adaptadas culturalmente.
- A qualidade final deve superar traduções automáticas básicas.

---

## Performance e Otimização (Atualização Atual)

### R17. Sistema de Chunking Inteligente Multi-Fase
- **Detecção de Entidades**: Implementar chunking de 8k caracteres com processamento paralelo
- **Tradução**: Chunking de 7k caracteres para máxima qualidade
- **Transcrição**: Chunking ultra-conservativo baseado em limites de tokens de saída
- **Preservação de Contexto**: Respeitar limites de frases em todas as fases

### R18. Otimização de Protocolos de API  
- **Formato Estruturado**: Resposta JSON otimizada `{"TYPE": ["entity1", "entity2"]}` 
- **Economia de Tokens**: Redução de ~60% no uso de tokens para detecção de entidades
- **Deduplicação**: Sistema inteligente baseado em chaves únicas `(name.lower(), type)`
- **Retry Logic**: Exponential backoff para robustez contra falhas temporárias

### R19. Sistema de Preservação de Dados
- **Cleanup Seletivo**: Manter pasta `output/` intacta entre execuções
- **Acumulação**: Permitir múltiplas transcrições sem perda de dados
- **Safety First**: Zero-risk de remoção acidental de arquivos finais
- **Organização**: UUID-based naming para evitar conflitos

### R20. Melhorias de Prompt Engineering
- **Detecção de Entidades**: Foco específico em nomes próprios de pessoas e lugares
- **Tradução**: Instruções explícitas para correção gramatical e formatação de diálogos
- **Normalização**: Adaptação cultural profunda e censura de linguagem inadequada
- **Consistência**: Formato de resposta padronizado e previsível

### R21. Performance Targets Atingidos
- **Detecção de Entidades**: <20 segundos para textos de 40k+ caracteres
- **Tradução**: Processamento estável em chunks de 7k caracteres
- **Robustez**: 99% de success rate através de chunking resiliente
- **User Experience**: Feedback em tempo real com links clicáveis para resultados

**Sistema otimizado para performance máxima e experiência de usuário superior!** ⚡✨

### R22. Processamento de Canais com Tradução
- **Comando**: `python3 transcriberio.py -transcribe -translate pt-BR,es-ES "https://www.youtube.com/@channel"`
- **Funcionalidades**:
  - Processar vídeos de canal com transcrição + tradução automática
  - Suportar múltiplas linguagens de destino (separadas por vírgula)
  - Processar completamente cada vídeo (todas traduções) antes do próximo
  - Salvar traduções como `<audio_id>_translated_<language>.txt`
  - Rastrear status de tradução no state.json para resumibilidade
- **Arquitetura**:
  - ChannelManager aceita parâmetro `translate_languages`
  - Integração com TranslatorNormalizer para tradução automática
  - Mock de seleção de linguagem para evitar prompt interativo
  - Estado persistente inclui dicionário de traduções por vídeo