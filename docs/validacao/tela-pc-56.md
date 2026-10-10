# Visualizador do PC — Android 56

## Implementação

- WebRTC H.264 + Opus; conexão direta quando possível e TURN autenticado na Oracle quando necessária. Sinalização usa o pareamento existente, sem cadastrar IP, URL ou token novos no app.
- TURN escuta UDP/TCP 3478 e usa UDP 49160–49200. Credenciais HMAC temporárias, secret apenas no PC/Oracle. API exige dispositivo pareado.
- Um portal ScreenCast compartilhado. Sessões RTC recebem heartbeat mesmo quando a imagem está parada e expiram após 40 segundos sem cliente. Encerramento libera pipeline e, após inatividade, portal/fd.
- Monitores vêm das fontes autorizadas. Captura composta do KDE é recortada pela geometria física; a saída virtual do portal não vira um monitor extra no seletor.
- Encoder OpenH264 com modo camera, complexidade baixa e slices paralelos. Relógio monotônico independente da atualização da tela, evitando desacelerar também o áudio. Keyframes após conexão e a cada dois segundos permitem recuperar imagem parada.
- Alta: até 1920×1080, alvo 60 FPS/8 Mbps. Equilibrada: até 1280×720, alvo 30 FPS/4 Mbps. Aspecto preservado; limites valem também para monitores verticais.
- H.264 constrained baseline com teto negociado 4.2, conferido nas capacidades do decoder. Caps do emissor anunciam o teto; SPS pode usar um nível menor em qualidade reduzida. Dispositivo incompatível usa MJPEG sem ficar alternando continuamente.
- Renderer TextureView/EGL integrado ao Compose: centralização por aspecto, clipping, pinça e duplo toque; pan apenas na parte ampliada que excede o viewport. Fullscreen, rotação e PiP compartilham a sessão, sem reconectar para alterar orientação.
- Áudio stereo como mídia, mute preservado; fallback PCM agora trata escritas parciais. Troca de monitor cancela HTTP/stream anterior. Tela estática envia keepalive no MJPEG.

## Validação

- Build APK 56 e instrumentação bem-sucedidos; 174 testes unitários Android passaram.
- 19 testes Python passaram, incluindo fonte autorizada, recorte dos monitores, heartbeat de imagem estática, monitor inválido sem derrubar sessão válida, erro GStreamer, credenciais TURN/autenticação e timeout do publicador.
- Moto G22 real: fullscreen, rotação em ambas direções sem trocar sessão, duplo toque/zoom, seleção persistente do segundo monitor. Captura de tela conferida visualmente.
- Vídeo H.264 e áudio nos dois monitores, diretamente e com ICE forçado a relay na Oracle. Alta observada em cerca de 32–40 FPS local e 29–39 FPS pela Oracle, com conteúdo em movimento. Sem perda de pacotes nos ensaios finais. RTT da rota aproximadamente 6 ms local / 24 ms relay; não é medida do atraso total da imagem.
- Qualidade equilibrada também passou com relay forçado: 1280×720 e 900×720, mantendo aspecto; áudio contínuo, sem underrun do AudioTrack nos logs.
- APK instalado com mesma assinatura, sem desinstalar. Assistente Emily e overlay conferidos e restaurados após instrumentação.

## Limites e itens preservados

- 60 FPS é alvo, não garantia: CPU, conteúdo, rede e decoder afetam o resultado. Drivers de GPU não foram alterados; o encoder disponível neste PC é OpenH264 em CPU.
- TURN foi validado forçando a rota pela Oracle enquanto o celular estava no Wi-Fi. Não houve ensaio físico numa operadora 4G diferente.
- Emissor para TV e controle remoto não foram migrados; permanecem nas implementações existentes. O trabalho é no visualizador Android e no serviço compartilhado de captura.

## Publicação

APK 56 instalado e publicado na Oracle. Montagem remota conferiu o hash integral; manifesto HTTPS e tamanho/SHA-256 conferidos com o APK local, download parcial validado. Manifesto e APK locais também atualizados. O publicador passou a usar IPv4/IPQoS=none após sucesso dessa conexão quando SSH com opções padrão expirava; upload anterior foi reaproveitado.
