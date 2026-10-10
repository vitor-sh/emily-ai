const Player = {
  playlist: [],
  indice: -1,
  tocando: false,
  // loop: 0 = desligado · 1 = repete a playlist · 2 = repete a música atual
  loop: 1,
  shuffle: false,
  player: null,       // objeto YT.Player
  pronto: false,
  _historico: [],
  // Fila do shuffle: ordem embaralhada que se percorre até o fim antes de
  // reembaralhar. Garante que não repita música até passar a playlist toda.
  _filaShuffle: [],
  _posShuffle: -1,
  _timer: null,       // intervalo que atualiza seek/tempo
  _duracao: 0,
  _buscando: false,   // true enquanto o usuário arrasta o seek (não atualiza)
  _playlistAtivaSalva: 'default',
  _faixaAtual: null,
  _filaFavoritas: false,
  _videoEsperado: null,
  _minimizada: false,
  _mutado: false,
  _falhasTentadas: new Set(),
  _faixaConfirmada: false,
  _ignorarEventos: false,
  _trocaEm: 0,

  async carregarPlaylist() {
    const videoAtual = this._faixaAtual?.video_id || this._videoEsperado;
    this._filaFavoritas = false;
    const geral = await carregarGeral();
    this._playlistAtivaSalva = geral.ativa || 'default';
    this.playlist = (geral.playlists[this._playlistAtivaSalva]?.musicas) || [];
    this.indice = videoAtual
      ? this.playlist.findIndex(m => m.video_id === videoAtual)
      : Math.min(this.indice, this.playlist.length - 1);
    if (videoAtual && this.indice < 0) this._historico = [];
    if (!this.playlist.length) this.indice = -1;
    if (this.shuffle) this._embaralhar();
  },

  // Restaura volume, loop, shuffle e a música/posição salvas do boot anterior.
  async restaurar() {
    const est = await tenta('player_estado');
    await window.EmilyMusic?.pollOffline();
    if (!est) return;
    if (typeof est.volume === 'number') {
      const s = $('#player-vol');
      if (s) s.value = est.volume;
      this.definirVolume(est.volume, { persistir: false });
    }
    if (typeof est.loop === 'number') this.loop = est.loop;
    if (typeof est.shuffle === 'boolean') this.shuffle = est.shuffle;
    if (est.playlist) this._playlistAtivaSalva = est.playlist;
    this._pintaControles();

    // Se tinha uma música tocando antes, carrega o player pausado nela, no
    // exato segundo salvo (o onReady do _criarPlayer trata o _resumoRestaurado).
    if (est.video_id && est.posicao >= 0) {
      const g = await carregarGeral();
      if (g && g.playlists) {
        const alvo = (g.playlists[est.playlist] || g.playlists['default'] || {}).musicas || [];
        const idx = alvo.findIndex(m => m.video_id === est.video_id);
        if (idx >= 0) {
          this.playlist = alvo;
          this.indice = idx;
           this._faixaAtual = alvo[idx];
           this._videoEsperado = est.video_id;
          _playlistsGeral.ativa = est.playlist || 'default';
          this._resumoRestaurado = { video_id: est.video_id, posicao: est.posicao };
          this._pintaBarra();
          // Sobe o iframe (que estava ocioso) pra posicionar a música salva.
          if(window.EmilyMusicAudio?.restaurarLocal(est.video_id,est.posicao))return;
          this._carregarIframe();
        }
      }
    }
  },

  // Retoma o volume do slider — o bug antigo era hardcode 100 aqui, que
  // ignorava o volume escolhido a cada troca de música.
  _volumeAtual() {
    const s = $('#player-vol');
    return s ? Number(s.value) || 0 : 100;
  },

  _carregarIframe() {
    if (this.pronto || this._carregando) return;
    this._carregando = true;
    if (window.YT && YT.Player) {
      // API já carregada (reload, segunda chamada): cria direto, sem recarregar.
      this._criarPlayer();
      return;
    }
    const tag = document.createElement('script');
    tag.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(tag);
    window.onYouTubeIframeAPIReady = () => this._criarPlayer();
  },

  _criarPlayer() {
    this.player = new YT.Player('yt-host', {
      height: '180', width: '320',
      playerVars: { autoplay: 1, controls: 0, playsinline: 1, rel: 0 },
      events: {
        onReady: () => {
          if(window.EmilyMusicAudio?.localActive){window.EmilyMusicAudio.ytReady=true;return;}
          this.pronto = true;
          this._carregando = false;
          try {
            this.player.setVolume(this._volumeAtual());
            if (this._mutado || this._volumeAtual() === 0) this.player.mute();
            else this.player.unMute();
          } catch {}
          // Restaura a música que tocava antes do boot: carrega, posiciona no
          // exato segundo salvo e fica PAUSADA (não sai tocando sozinha).
          if (this._resumoRestaurado) {
            const r = this._resumoRestaurado;
            this._resumoRestaurado = null;
            try {
              this.player.loadVideoById(r.video_id);
              this.player.pauseVideo();
              setTimeout(() => {
                try {
                  this.player.seekTo(r.posicao, true);
                  this.player.pauseVideo();
                } catch {}
              }, 350);
              this.tocando = false;
              this._pintaControles();
            } catch {}
          }
          if (this._fila) { const f = this._fila; this._fila = null; f(); }
        },
        onStateChange: (e) => {
          // Reafirma audível ao entrar em playing/buffering.
          if (e.data === 1 || e.data === 3) {
            try {
              this.player.setVolume(this._volumeAtual());
              if (this._mutado || this._volumeAtual() === 0) this.player.mute();
              else if (this.player.isMuted()) this.player.unMute();
            } catch {}
          }
          this._estado(e.data);
        },
        onError: (e) => {
          if (this._ignorarEventos || window.EmilyMusicAudio?.localActive) return;
          console.warn('[PLAYER] erro do YouTube:', e.data);
          const video = this._videoCarregado();
          if (video && this._videoEsperado && video !== this._videoEsperado) return;
          this._marcarEstadoVisual('erro');
          this.proxima({ erro: true });
        },
      },
    });
  },

  // Toca com som garantido: unmute + volume do slider + play, na ordem.
  _darPlay() {
    try {
      this.player.unMute();
      this.player.setVolume(this._volumeAtual());
      this.player.playVideo();
    } catch {}
  },

  _videoCarregado() {
    try { return this.player?.getVideoData?.().video_id || ''; } catch { return ''; }
  },

  _estado(estado) {
    if (this._ignorarEventos) return;
    // 1 = tocando, 2 = pausado, 0 = terminou, 3 = buffering, 5 = parado (cued)
    const carregado = this._videoCarregado();
    // A API pode entregar ENDED/PAUSED da faixa antiga depois de loadVideoById.
    // Sem validar o id, esse callback tardio avançava duas músicas de uma vez.
    if (carregado && this._videoEsperado && carregado !== this._videoEsperado) return;
    if (estado === 0) {
      const desdeTroca = performance.now() - this._trocaEm;
      let terminouMesmo = false;
      try {
        const duracao = Number(this.player?.getDuration?.() || 0);
        const posicao = Number(this.player?.getCurrentTime?.() || 0);
        terminouMesmo = duracao > 0 && posicao >= duracao - Math.max(1.25, duracao * .01);
      } catch {}
      // Alguns embeds zeram a duração logo após ENDED. Nesse caso a faixa
      // confirmada + janela temporal é o fallback; posição conhecida vence.
      if (this._faixaConfirmada && (terminouMesmo || (this._duracao <= 0 && desdeTroca > 900))) {
        this.proxima({ natural: true });
      }
      return;
    }
    // Buffering (3) conta como "tocando" pro ícone: não faz sentido o botão
    // mostrar play enquanto a música está carregando pra tocar.
    this.tocando = estado === 1 || estado === 3;
    if (estado === 1) {
      this._faixaConfirmada = true;
      this._falhasTentadas.clear();
      this._iniciarTimer();
      this._marcarEstadoVisual('tocando');
    } else if (estado === 2 || estado === 3 || estado === 5) {
      this._pararTimer();
      this._marcarEstadoVisual(estado === 3 ? 'carregando' : 'pausado');
      if (estado === 2) this._persistir();
    }
    this._pintaControles();
    this._atualizarMediaSession();
  },

  // ── Seek bar / tempo ──────────────────────────────────────────
  _fmt(t) {
    if (!isFinite(t) || t < 0) t = 0;
    const m = Math.floor(t / 60), s = Math.floor(t % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  },
  _atualizarTempo() {
    if (!this.player || !this.pronto || this.indice < 0) return;
    try {
      const dur = this.player.getDuration();
      const cur = this.player.getCurrentTime();
      if (dur > 0 && isFinite(dur)) {
        this._duracao = dur;
        const seek = $('#player-seek');
        if (seek && !this._buscando) {
          const pct = Math.min(100, (cur / dur) * 100);
          seek.value = pct;
          seek.style.setProperty('--seek', pct + '%');
        }
        const tCur = $('#player-time-cur');
        if (tCur) tCur.textContent = this._fmt(cur);
        const tDur = $('#player-time-dur');
        if (tDur) tDur.textContent = this._fmt(dur);
      }
    } catch {}
  },
  _iniciarTimer() {
    this._pararTimer();
    this._timer = setInterval(() => this._atualizarTempo(), 500);
    this._atualizarTempo();
  },
  _pararTimer() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  },

  // ── Shuffle: fila embaralhada de verdade ──────────────────────
  _embaralhar() {
    const fila = this.playlist.map((_, i) => i).filter(i => i !== this.indice);
    for (let i = fila.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [fila[i], fila[j]] = [fila[j], fila[i]];
    }
    this._filaShuffle = fila;
    this._posShuffle = -1;
  },
  _proximoShuffle() {
    if (this.playlist.length === 1) return 0;
    if (!this._filaShuffle.length) this._embaralhar();
    this._posShuffle += 1;
    if (this._posShuffle >= this._filaShuffle.length) {
      // Acabou a fila: reembaralha sem repetir a última faixa na emenda.
      const atual = this._filaShuffle[this._filaShuffle.length - 1];
      this._embaralhar();
      if (this._filaShuffle.length > 1 && this._filaShuffle[0] === atual) {
        [this._filaShuffle[0], this._filaShuffle[1]] = [this._filaShuffle[1], this._filaShuffle[0]];
      }
      this._posShuffle = 0;
    }
    return this._filaShuffle[this._posShuffle];
  },

  _zerarSeek() {
    const seek = $('#player-seek');
    if (seek) { seek.value = 0; seek.style.setProperty('--seek', '0%'); }
    const tCur = $('#player-time-cur');
    if (tCur) tCur.textContent = '0:00';
    const tDur = $('#player-time-dur');
    if (tDur) tDur.textContent = '0:00';
    this._duracao = 0;
  },

  tocar(indice, { registrarHistorico = true } = {}) {
    if (!this.playlist.length) return;
    if (indice == null) {
      indice = this.shuffle ? this._proximoShuffle() : 0;
    }
    indice = ((indice % this.playlist.length) + this.playlist.length) % this.playlist.length;
    if (registrarHistorico && this.indice >= 0 && this.indice !== indice) {
      this._historico.push(this.indice);
      if (this._historico.length > 100) this._historico.shift();
    }
    this.indice = indice;
    const m = this.playlist[this.indice];
    if (!m?.video_id) return;
    this._faixaAtual = m;
    if(m.origem)this._playlistAtivaSalva=m.origem;
    this._videoEsperado = m.video_id;
    this._faixaConfirmada = false;
    this._ignorarEventos = false;
    this._trocaEm = performance.now();
    this._carregarIframe();
    const iniciar = () => {
      // A fila de inicialização pode ter sido substituída antes da API ficar
      // pronta. Só a seleção mais recente tem autorização pra tocar.
      if (this._videoEsperado !== m.video_id) return;
      this.player.loadVideoById(m.video_id);
      this.player.setVolume(this._volumeAtual());
      if (this._mutado || this._volumeAtual() === 0) this.player.mute();
      else this.player.unMute();
      this.player.playVideo();
      this.tocando = true;
      this._zerarSeek();
      this._pintaBarra();
      this._pintaControles();
      this._pintaModal();
      this._marcarEstadoVisual('carregando');
      this._atualizarMediaSession();
      this._persistir();
    };
    if (this.pronto) iniciar();
    else this._fila = iniciar;
  },

  _repetirAtual() {
    // Preserva a fonte e o buffer: loadVideoById/audio.load descartam a
    // reprodução anterior e podem exigir outra requisição de mídia.
    const id = this.playlist[this.indice]?.video_id;
    if (!id) return;
    try {
      if (!this.pronto || !this.player || this._ignorarEventos ||
          this.player.getVideoData?.().video_id !== id) {
        this.tocar(this.indice, { registrarHistorico: false });
        return;
      }
      this._faixaConfirmada = false;
      this._trocaEm = performance.now();
      this.player.seekTo(0, true);
      this.player.playVideo();
      this.tocando = true;
      this._iniciarTimer();
      this._pintaControles();
      this._marcarEstadoVisual('tocando');
      this._atualizarMediaSession();
      this._persistir();
    } catch {
      this.tocar(this.indice, { registrarHistorico: false });
    }
  },

  proxima({ manual = false, natural = false, erro = false } = {}) {
    if (!this.playlist.length) return;
    this._pararTimer();
    if (natural && !erro && (this.loop === 2 || this.loop === 1 && this.playlist.length === 1)) {
      this._repetirAtual();
      return;
    }
    if (erro && this._videoEsperado) {
      this._falhasTentadas.add(this._videoEsperado);
      if (this._falhasTentadas.size >= this.playlist.length) {
        this.pausar();
        this._marcarEstadoVisual('erro');
        toast('Nenhuma faixa desta playlist pôde ser reproduzida', 'erro');
        return;
      }
    }
    let i;
    if (this.shuffle) {
      i = this._proximoShuffle();
    } else {
      i = this.indice + 1;
      if (i >= this.playlist.length) {
        if (natural && this.loop === 0 && !erro) { this.pausar(); return; }
        i = 0;
      }
    }
    this.tocar(i);
  },

  anterior(forcarFaixa = false) {
    if (!this.playlist.length) return;
    // Com mais de 3s, "anterior" reinicia a faixa — comportamento esperado
    // de players reais. Um segundo clique volta de fato no histórico.
    try {
      if (!forcarFaixa && (this.player?.getCurrentTime?.() || 0) > 3) {
        this.player.seekTo(0, true);
        return;
      }
    } catch {}
    if (this._historico.length) {
      return this.tocar(this._historico.pop(), { registrarHistorico: false });
    }
    this.tocar((this.indice - 1 + this.playlist.length) % this.playlist.length,
      { registrarHistorico: false });
  },

  playPause() {
    if (!this.player || !this.pronto || this.indice < 0) return;
    this.tocando ? this.player.pauseVideo() : this.player.playVideo();
  },

  pausar() {
    this._pararTimer();
    try { this.player && this.player.pauseVideo(); } catch {}
    this.tocando = false;
    this._marcarEstadoVisual('pausado');
    this._pintaControles();
    this._atualizarMediaSession();
  },

  alternarLoop() {
    // 0 → 1 (playlist) → 2 (música única) → 0
    this.loop = (this.loop + 1) % 3;
    this._pintaControles();
    this._persistir();
  },
  alternarShuffle() {
    this.shuffle = !this.shuffle;
    if (this.shuffle) this._embaralhar();
    this._pintaControles();
    this._persistir();
  },

  _marcarEstadoVisual(estado) {
    const barra = $('#player-barra');
    if (barra) barra.dataset.estado = estado;
    const sub = $('#player-sub');
    if (!sub) return;
    const base = this.playlist.length
      ? `${this.indice + 1} de ${this.playlist.length} · ${this._playlistAtivaSalva === 'default' ? 'Minha seleção' : this._playlistAtivaSalva === '__avulsa__' ? 'Reprodução avulsa' : this._playlistAtivaSalva}`
      : 'Emily Music';
    sub.textContent = estado === 'carregando' ? `Carregando · ${base}`
      : estado === 'erro' ? `Não foi possível tocar · ${base}`
        : estado === 'pausado' ? `Pausada · ${base}` : base;
  },

  _atualizarMediaSession() {
    if (!('mediaSession' in navigator)) return;
    const m = this._faixaAtual || this.playlist[this.indice];
    if (!m) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({
        title: m.titulo || 'Sem título', artist: 'Emily Music',
        album: this._playlistAtivaSalva || 'Playlist',
        artwork: m.thumb ? [{ src: m.thumb, sizes: '320x180' }] : [],
      });
      navigator.mediaSession.playbackState = this.tocando ? 'playing' : 'paused';
    } catch {}
  },

  // Persiste o estado atual no backend (volume, loop, shuffle, posição).
  _persistir() {
    const playlistNome = this._playlistAtivaSalva || _playlistsGeral.ativa || 'default';
    tenta('player_salvar_estado', {
      volume: this._mutado ? 0 : this._volumeAtual(),
      loop: this.loop,
      shuffle: this.shuffle,
      playlist: playlistNome,
      indice: this.indice,
      video_id: this.playlist[this.indice]?.video_id || null,
      posicao: this.player && this.pronto ? (this.player.getCurrentTime() || 0) : 0,
    });
  },

  fechar() {
    this._pararTimer();
    this._persistir();
    this._ignorarEventos = true;
    try { this.player && this.player.stopVideo(); } catch {}
    $('#player-barra').hidden = true;
    document.body.classList.remove('com-player');
    document.getElementById('player-resgate')?.remove();
    this._minimizada = false;
    this.tocando = false;
    this._pintaControles();
  },

  _pintaBarra() {
    const m = this._faixaAtual || this.playlist[this.indice];
    if (!m) return;
    const capa = window.EmilyMusic?.offline.faixas[m.video_id]?.thumb || m.thumb;
    $('#player-thumb').src = capa;
    $('#player-thumb').alt = `Capa de ${m.titulo}`;
    const ambiente = $('#player-ambiente');
    if (ambiente) ambiente.src = capa;
    $('#player-titulo').textContent = m.titulo;
    this._marcarEstadoVisual(this.tocando ? 'tocando' : 'pausado');
    if (!this._minimizada) {
      $('#player-barra').hidden = false;
      document.body.classList.add('com-player');
      document.getElementById('player-resgate')?.remove();
    } else this._atualizarResgate();
  },

  _pintaControles() {
    const play = $('#player-play');
    if (!play) return;
    play.classList.toggle('tocando', this.tocando);
    play.classList.toggle('pausado', !this.tocando);
    play.setAttribute('aria-label', this.tocando ? 'Pausar' : 'Tocar');
    // Loop 3 estados: 0=off, 1=playlist (ativa+pontinho), 2=música (ativa+badge "1")
    const btnLoop = $('#player-loop');
    const badge = $('#loop-badge');
    if (this.loop === 0) {
      btnLoop.classList.remove('ativa');
      btnLoop.setAttribute('aria-pressed', 'false');
      btnLoop.title = 'Sem repetir';
      if (badge) badge.hidden = true;
    } else if (this.loop === 1) {
      btnLoop.classList.add('ativa');
      btnLoop.setAttribute('aria-pressed', 'true');
      btnLoop.title = 'Repetir playlist';
      if (badge) badge.hidden = true;
    } else {
      btnLoop.classList.add('ativa');
      btnLoop.setAttribute('aria-pressed', 'true');
      btnLoop.title = 'Repetir esta música';
      if (badge) badge.hidden = false;
    }
    // Shuffle on/off
    const btnShuf = $('#player-shuffle');
    btnShuf.classList.toggle('ativa', this.shuffle);
    btnShuf.setAttribute('aria-pressed', String(this.shuffle));
    btnShuf.title = this.shuffle ? 'Aleatório ligado' : 'Aleatório';
  },

  definirVolume(valor, { persistir = true } = {}) {
    try {
      valor = Math.max(0, Math.min(100, Math.round(Number(valor) || 0)));
      if (this.player && this.pronto) {
        this.player.setVolume(valor);
        if (valor > 0) { this.player.unMute(); this._mutado = false; }
        if (valor === 0) { this.player.mute(); this._mutado = true; }
      }
      const alto = $('#vol-ico-alto'), mudo = $('#vol-ico-mudo');
      if (alto && mudo) { alto.hidden = valor === 0; mudo.hidden = valor !== 0; }
      const s = $('#player-vol');
      if (s) { s.value = valor; s.style.setProperty('--vol', valor + '%'); }
      this._mutado = valor === 0;
      const pct = $('#player-vol-pct');
      if (pct) pct.textContent = valor + '%';
      if (persistir) this._persistir();
    } catch {}
  },

  minimizar() {
    $('#player-barra').hidden = true;
    document.body.classList.remove('com-player');
    this._minimizada = true;
    this._atualizarResgate();
  },

  _atualizarResgate() {
    if (!this._minimizada || !this._faixaAtual) return;
    let resgate = document.getElementById('player-resgate');
    if (!resgate) {
      resgate = document.createElement('button');
      resgate.id = 'player-resgate';
      resgate.type = 'button';
      resgate.onclick = () => {
        this._minimizada = false;
        $('#player-barra').hidden = false;
        document.body.classList.add('com-player');
        resgate.remove();
      };
      document.body.appendChild(resgate);
    }
    const m = this._faixaAtual;
    resgate.title = `Expandir player · ${m.titulo}`;
    resgate.setAttribute('aria-label', resgate.title);
    resgate.innerHTML = `<img src="${esc(m.thumb)}" alt=""><span class="player-resgate-eq" aria-hidden="true"><i></i><i></i><i></i></span>`;
  },

  _pintaModal() {
    if ($('#modal-player').hidden) return;
    desenharPlaylist();
  },
};

// Dados do modal de playlists (carregados do backend)
let _playlistsGeral = { playlists: {}, ativa: 'default', favoritos: {} };
let _somenteFavoritas = false;

async function carregarGeral() {
  const g = await tenta('playlist_geral');
  if (g) _playlistsGeral = g;
  return _playlistsGeral;
}

function desenharSidebar() {
  if(window.EmilyMusic){window.EmilyMusic.sidebar();return;}
  const nav = $('#pl-sidebar-lista');
  if (!nav) return;
  nav.innerHTML = '';
  for (const nome of Object.keys(_playlistsGeral.playlists)) {
    const dados = _playlistsGeral.playlists[nome];
    const qtd = dados.quantidade || (dados.musicas || []).length;
    const foto = dados.foto || '';
    const item = document.createElement('button');
    item.className = 'pl-sb-item' + (nome === _playlistsGeral.ativa ? ' ativa' : '');
    // Foto/icone
    const fotoEl = document.createElement('span');
    fotoEl.className = 'pl-sb-foto';
    if (foto) fotoEl.innerHTML = `<img src="${esc(foto)}" alt="">`;
    else fotoEl.innerHTML = '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.8"><path d="M21 19V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2z"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>';
    item.appendChild(fotoEl);
    // Nome
    const nomeEl = document.createElement('span');
    nomeEl.className = 'pl-sb-nome';
    nomeEl.textContent = nome;
    item.appendChild(nomeEl);
    // Quantidade
    const count = document.createElement('span');
    count.className = 'pl-sb-count';
    count.textContent = qtd;
    item.appendChild(count);
    // Ações (renomear, foto, excluir)
    const acoes = document.createElement('span');
    acoes.className = 'pl-sb-acoes';
      // Renomear
      const ren = document.createElement('button');
      ren.title = 'Renomear';
      ren.innerHTML = '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.8" class="pbtn-mini"><path d="M17 3a2.85 2.85 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>';
      ren.onclick = (ev) => { ev.stopPropagation(); abrirModalPlaylist(nome, dados); };
      acoes.appendChild(ren);
      // Foto (câmera)
      const fotoBtn = document.createElement('button');
      fotoBtn.title = 'Foto';
      fotoBtn.innerHTML = '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.8"><path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/></svg>';
      fotoBtn.onclick = (ev) => { ev.stopPropagation(); abrirModalPlaylist(nome, dados); };
      acoes.appendChild(fotoBtn);
      // Excluir (só pra não-default — a padrão não se apaga)
      if (nome !== 'default') {
        const del = document.createElement('button');
        del.className = 'pl-sb-del';
        del.title = 'Apagar playlist';
        del.innerHTML = '<svg viewBox="0 0 24 24" style="width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.8"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>';
        del.onclick = async (ev) => {
          ev.stopPropagation();
          if (!confirm(`Apagar a playlist "${nome}"?`)) return;
          const ok = await tenta('playlist_apagar', nome);
          if (ok) {
            _playlistsGeral.ativa = 'default';
            await carregarGeral();
            await Player.carregarPlaylist();
            desenharSidebar();
            desenharPlaylist();
          }
        };
        acoes.appendChild(del);
      }
      item.appendChild(acoes);
    item.onclick = async () => {
      const ok = await tenta('playlist_selecionar', nome);
      if (ok) {
        _playlistsGeral.ativa = nome;
        await Player.carregarPlaylist();
        desenharSidebar();
        desenharPlaylist();
      }
    };
    nav.appendChild(item);
  }
}

// ── Modal de criar/editar playlist ──────────────────────────────
let _editandoPlaylist = null;
function abrirModalPlaylist(nome, dados) {
  _editandoPlaylist = nome ? { nome, foto: dados?.foto || '' } : null;
  const overlay = $('#pl-modal-overlay');
  if (!overlay) return;
  overlay.hidden = false;
  const titulo = $('#pl-modal-titulo');
  titulo.textContent = nome ? 'Editar playlist' : 'Nova playlist';
  const input = $('#pl-modal-nome');
  input.readOnly = nome === 'default';
  input.value = nome === 'default' ? 'Minha seleção' : (nome || '');
  input.focus();
  input.select();
  const confirmar = $('#pl-modal-confirmar');
  confirmar.textContent = nome ? 'Salvar' : 'Criar';
  const fotoImg = $('#pl-modal-foto-img');
  if (dados?.foto) fotoImg.innerHTML = `<img src="${esc(dados.foto)}" alt="">`;
  else fotoImg.innerHTML = '<svg viewBox="0 0 24 24"><path d="M21 19V5a2 2 0 00-2-2H5a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2z"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>';
  const fotoInput = $('#pl-modal-foto-input');
  if (fotoInput) fotoInput.value = '';
  overlay.classList.remove('fechando');
  overlay.classList.add('abrindo');
  setTimeout(() => overlay.classList.remove('abrindo'), 50);
}

function fecharModalPlaylist() {
  const overlay = $('#pl-modal-overlay');
  if (!overlay) return;
  overlay.classList.add('fechando');
  setTimeout(() => {
    overlay.hidden = true;
    overlay.classList.remove('fechando');
    _editandoPlaylist = null;
  }, 200);
}

function desenharPlaylist() {
  if(window.EmilyMusic){window.EmilyMusic.render();return;}
  const lista = $('#pl-lista');
  if (!lista) return;
  lista.innerHTML = '';
  const info = $('#pl-info');
  const exibidas = Player.playlist
    .map((m, indice) => ({ m, indice }))
    .filter(({ m }) => !_somenteFavoritas || !!_playlistsGeral.favoritos?.[m.video_id]);
  if (info) info.innerHTML = `<strong>${esc(_playlistsGeral.ativa)}</strong><span>${exibidas.length} faixa${exibidas.length === 1 ? '' : 's'}${_somenteFavoritas ? ' favorita' + (exibidas.length === 1 ? '' : 's') : ''}</span>`;
  if (!exibidas.length) {
    lista.innerHTML = `<div class="pl-vazia">${svg(_somenteFavoritas ? ICO.cerebro : ICO.musica)}<strong>${_somenteFavoritas ? 'Nenhuma favorita aqui' : 'Sua playlist está vazia'}</strong><span>${_somenteFavoritas ? 'Marque o coração de uma faixa para ela aparecer aqui.' : 'Busque uma música acima para começar.'}</span></div>`;
    return;
  }
  exibidas.forEach(({ m, indice: i }, posicao) => {
    const div = document.createElement('div');
    const atual = i === Player.indice;
    div.className = 'pl-item' + (atual ? ' tocando' : '');
    const marca = atual
      ? '<span class="pl-eq"><i></i><i></i><i></i></span>'
      : `<small>${posicao + 1}</small>`;
    div.innerHTML =
      `<img src="${esc(m.thumb)}" alt="">` +
      `<div class="pl-item-txt"><strong>${esc(m.titulo)}</strong>${marca}</div>`;
    div.onclick = () => { Player.tocar(i); };

    // Coração de favorito
    const fav = document.createElement('button');
    const ehFav = !!(_playlistsGeral.favoritos && _playlistsGeral.favoritos[m.video_id]);
    fav.className = 'pl-item-fav' + (ehFav ? ' ativo' : '');
    fav.title = ehFav ? 'Desfavoritar' : 'Favoritar';
    fav.innerHTML = '<svg viewBox="0 0 24 24"><path d="M12 21s-6.7-4.35-9.33-8.11C.9 10.2 1.9 6.5 4.9 5.3a5 5 0 017.1 1.9 5 5 0 017.1-1.9c3 1.2 4 4.9 2.23 7.59C18.7 16.65 12 21 12 21z"/></svg>';
    fav.onclick = async (ev) => {
      ev.stopPropagation();
      const novo = !ehFav;
      await tenta('playlist_favoritar', m.video_id, novo);
      if (_playlistsGeral.favoritos) {
        if (novo) _playlistsGeral.favoritos[m.video_id] = true;
        else delete _playlistsGeral.favoritos[m.video_id];
      }
      desenharPlaylist();
    };
    div.appendChild(fav);

    const del = document.createElement('button');
    del.className = 'icone-btn mini pl-item-del';
    del.title = 'Remover da playlist';
    del.innerHTML = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';
    del.onclick = async (ev) => {
      ev.stopPropagation();
      await tenta('playlist_remover', m.video_id);
      await carregarGeral();
      await Player.carregarPlaylist();
      desenharSidebar();
      desenharPlaylist();
    };
    div.appendChild(del);
    lista.appendChild(div);
  });
}

// ── Busca com prévia (resultados antes de adicionar) ────────────
let _debounceBusca = null;
async function buscarPreview(q) {
  if(window.EmilyMusic){return window.EmilyMusic.search(q);}
  const preview = $('#pl-preview');
  if (!preview) return;
  if (!q) { preview.hidden = true; preview.innerHTML = ''; return; }
  const erro = $('#pl-erro');
  if (erro) erro.hidden = true;
  preview.hidden = false;
  preview.innerHTML = '<p class="pl-prev-titulo">Buscando…</p>';
  const r = await tenta('playlist_buscar_preview', q);
  if (!r || r.erro) {
    preview.innerHTML = `<p class="pl-prev-titulo">${esc(r && r.erro ? r.erro : 'Sem resultados')}</p>`;
    return;
  }
  const res = r.resultados || [];
  preview.innerHTML = `<p class="pl-prev-titulo">${res.length} resultado${res.length > 1 ? 's' : ''} — clique pra adicionar</p>`;
  res.forEach(m => {
    const div = document.createElement('div');
    div.className = 'pl-prev-item';
    div.innerHTML =
      `<img src="${esc(m.thumb)}" alt="">` +
      `<div class="pl-prev-item-txt"><strong>${esc(m.titulo)}</strong></div>` +
      '<button class="pl-prev-add" title="Adicionar"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></button>';
    div.onclick = async () => {
      await tenta('playlist_adicionar', m.video_id, m.titulo, m.thumb);
      await carregarGeral();
      await Player.carregarPlaylist();
      desenharSidebar();
      desenharPlaylist();
      preview.hidden = true;
      preview.innerHTML = '';
    };
    preview.appendChild(div);
  });
}

function ligarPlayer() {
  // Instancia o modal de criar/editar playlist (template único, fora do palco)
  const tplModal = $('#tpl-modal-playlist');
  if (tplModal && !$('#pl-modal-overlay')) {
    document.body.appendChild(tplModal.content.cloneNode(true));
  }
  // Preenchimento do slider no boot (gradiente via CSS var --vol).
  const volSlider = $('#player-vol');
  if (volSlider) {
    volSlider.style.setProperty('--vol', volSlider.value + '%');
    const pct = $('#player-vol-pct');
    if (pct) pct.textContent = volSlider.value + '%';
  }
  const seekInit = $('#player-seek');
  if (seekInit) seekInit.style.setProperty('--seek', '0%');
  $('#btn-music').onclick = async () => {
    await carregarGeral();
    await Player.carregarPlaylist();
    $('#modal-player').hidden = false;
    desenharSidebar();
    desenharPlaylist();
    $('#pl-query').focus();
  };

  $('#pl-tocar-tudo').onclick = () => {
    const primeiro = Player.playlist.findIndex(m =>
      !_somenteFavoritas || !!_playlistsGeral.favoritos?.[m.video_id]);
    if (primeiro >= 0) Player.tocar(primeiro);
  };
  $('#pl-filtro-fav').onclick = (e) => {
    _somenteFavoritas = !_somenteFavoritas;
    e.currentTarget.classList.toggle('ativo', _somenteFavoritas);
    e.currentTarget.setAttribute('aria-pressed', String(_somenteFavoritas));
    desenharPlaylist();
  };

  $('#modal-player-fechar').onclick = () => { $('#modal-player').hidden = true; };
  $('#modal-player').onclick = (e) => {
    if (e.target.id === 'modal-player') $('#modal-player').hidden = true;
  };

  // Nova playlist — abre o modal bonito
  $('#pl-nova').onclick = () => abrirModalPlaylist('', {});

  // ── Modal de criar/editar playlist ──────────────────────────────
  // Foto: clique abre o seletor de arquivos
  const fotoModal = $('#pl-modal-foto');
  const fotoInput = $('#pl-modal-foto-input');
  if (fotoModal && fotoInput) {
    fotoModal.onclick = () => fotoInput.click();
    fotoInput.onchange = () => {
      const file = fotoInput.files && fotoInput.files[0];
      if (!file) return;
      if(!file.type.startsWith('image/') || file.size>5*1024*1024){toast('Escolha uma imagem de até 5 MB','erro');return;}
      const reader = new FileReader();
      reader.onload = (e) => {
        const dataUri = e.target.result;
        const img = $('#pl-modal-foto-img');
        if (img) img.innerHTML = `<img src="${dataUri}" alt="">`;
      };
      reader.readAsDataURL(file);
    };
  }
  // Fechar
  const fecharModal = () => fecharModalPlaylist();
  for (const el of $$('.pl-modal-fechar, #pl-modal-cancelar')) {
    if (el) el.onclick = fecharModal;
  }
  // Confirmar (criar ou salvar)
  $('#pl-modal-confirmar').onclick = async () => {
    const input = $('#pl-modal-nome');
    const nome = _editandoPlaylist?.nome === 'default' ? 'default' : (input.value || '').trim();
    if (!nome) return;
    // Pega a foto do data-uri que foi carregada
    const fotoImg = $('#pl-modal-foto-img');
    let foto = '';
    const img = fotoImg && fotoImg.querySelector('img');
    if (img) foto = img.src;
    if (_editandoPlaylist) {
      // Editar: renomear se mudou
      if (nome !== _editandoPlaylist.nome) {
        const r = await tenta('playlist_renomear', _editandoPlaylist.nome, nome);
        if (!r || r.erro) { alert(r?.erro || 'Não foi possível salvar. Tente novamente.'); return; }
      }
      // Foto se mudou
      if (foto !== _editandoPlaylist.foto) {
        await tenta('playlist_foto', nome, foto);
      }
    } else {
      // Criar nova
      const r = await tenta('playlist_criar', nome, foto);
      if (!r || r.erro) { alert(r?.erro || 'Não foi possível salvar. Tente novamente.'); return; }
    }
    if(window.EmilyMusic){
      if(_editandoPlaylist){if(Player._playlistAtivaSalva===_editandoPlaylist.nome)Player._playlistAtivaSalva=nome;for(const m of Player.playlist){if(m.origem===_editandoPlaylist.nome)m.origem=nome;}}
      window.EmilyMusic.view=nome;
      fecharModal();
      await window.EmilyMusic.refresh();
      window.EmilyMusic.go('playlist');
      return;
    }
    fecharModal();
    await carregarGeral();
    await Player.carregarPlaylist();
    desenharSidebar();
    desenharPlaylist();
  };
  // Enter no input confirma
  $('#pl-modal-nome').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') $('#pl-modal-confirmar').click();
  });

  // Busca com prévia — o Enter busca, não adiciona direto.
  $('#pl-form').onsubmit = async (e) => {
    e.preventDefault();
    clearTimeout(_debounceBusca);
    const q = $('#pl-query').value.trim();
    if (!q) return;
    buscarPreview(q);
  };
  // Prévia enquanto digita (debounce pra não bater no YouTube a cada tecla).
  $('#pl-query').addEventListener('input', (e) => {
    if(window.EmilyMusic)return; // O Music pesquisa somente por confirmação explícita.
    const q = e.target.value.trim();
    if (_debounceBusca) clearTimeout(_debounceBusca);
    if (!q) {
      if(window.EmilyMusic){window.EmilyMusic.searchSerial++;window.EmilyMusic.go('inicio');}
      const preview = $('#pl-preview');
      if (preview) { preview.hidden = true; preview.innerHTML = ''; }
      return;
    }
    _debounceBusca = setTimeout(() => buscarPreview(q), 450);
  });

  // ── Seek bar ───────────────────────────────────────────────
  const seek = $('#player-seek');
  if (seek) {
    seek.addEventListener('input', () => {
      Player._buscando = true;
      const pct = Number(seek.value) || 0;
      seek.style.setProperty('--seek', pct + '%');
      if (Player._duracao > 0) {
        const tCur = $('#player-time-cur');
        if (tCur) tCur.textContent = Player._fmt(Player._duracao * pct / 100);
      }
    });
    seek.addEventListener('change', () => {
      Player._buscando = false;
      if (Player.player && Player.pronto) {
        const pct = Number(seek.value) || 0;
        const alvo = Player._duracao * pct / 100;
        try { Player.player.seekTo(alvo, true); } catch {}
      }
    });
  }

  $('#player-play').onclick = () => {
    // playVideo/pauseVideo direto aqui: o clique É o gesto que o Chromium
    // exige pra áudio — chamar via objeto indireto às vezes perde a janela
    // de ativação (medido: autoplay bloqueado sem isso).
    const p = Player.player;
    if (!p || !Player.pronto || Player.indice < 0) return;
    if (Player.tocando) { p.pauseVideo(); Player.tocando = false; }
    else {
      p.setVolume(Player._volumeAtual());
      if (Player._mutado) p.mute(); else p.unMute();
      p.playVideo(); Player.tocando = true;
    }
    Player._pintaControles();
  };
  $('#player-next').onclick = () => Player.proxima({ manual: true });
  $('#player-prev').onclick = () => Player.anterior();
  $('#player-loop').onclick = () => Player.alternarLoop();
  $('#player-shuffle').onclick = () => Player.alternarShuffle();
  $('#player-fechar').onclick = () => Player.fechar();
  $('#player-vol').oninput = (e) => Player.definirVolume(Number(e.target.value));
  $('#player-minimizar').onclick = () => Player.minimizar();
  $('#player-mute').onclick = () => {
    const slider = $('#player-vol');
    try {
      if (Player.player && Player.pronto) {
        if (Player.player.isMuted()) { Player.definirVolume(Number(slider.value) || 100); }
        else Player.player.mute();
        const mudo = Player.player.isMuted();
        Player._mutado = mudo;
        $('#vol-ico-alto').hidden = mudo;
        $('#vol-ico-mudo').hidden = !mudo;
        Player._persistir();
      } else {
        // sem player ainda: alterna só o ícone
        Player._mutado = !Player._mutado;
        const alto = $('#vol-ico-alto');
        alto.hidden = !alto.hidden;
        $('#vol-ico-mudo').hidden = !alto.hidden;
      }
    } catch {}
  };

  // Clique no bloco de faixa abre a biblioteca.
  $('#player-faixa').onclick = async () => {
    await Player.carregarPlaylist();
    $('#modal-player').hidden = false;
    desenharPlaylist();
  };

  window.EmilyMusic?.init();

  // Teclas de mídia e controles da tela bloqueada do Windows, quando a
  // WebView expõe Media Session.
  if ('mediaSession' in navigator) {
    const acoes = {
      play: () => Player.player?.playVideo?.(),
      pause: () => Player.pausar(),
      nexttrack: () => Player.proxima({ manual: true }),
      previoustrack: () => Player.anterior(true),
      seekto: d => { if (Number.isFinite(d.seekTime)) Player.player?.seekTo?.(d.seekTime, true); },
      seekforward: d => Player.player?.seekTo?.((Player.player?.getCurrentTime?.() || 0) + (d.seekOffset || 10), true),
      seekbackward: d => Player.player?.seekTo?.(Math.max(0, (Player.player?.getCurrentTime?.() || 0) - (d.seekOffset || 10)), true),
    };
    Object.entries(acoes).forEach(([nome, fn]) => {
      try { navigator.mediaSession.setActionHandler(nome, fn); } catch {}
    });
  }
}

