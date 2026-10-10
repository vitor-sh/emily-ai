# Energia do PC

O recibo devolvido ao agendar indica comando aceito pelo executor, não uma observação física do PC desligado/suspenso. A desconexão após o prazo previsto é esperada. Não fazer novas consultas só para provar essa ação; pedidos compostos ainda precisam completar suas outras etapas.

O Android guarda o último recibo e, somente para consultas de energia que falham por indisponibilidade, pode explicar a desconexão esperada nos dois minutos após o horário previsto. Antes desse horário, sem recibo, após expirar ou diante de erro de autenticação, não converte falhas em sucesso. Cancelamento confirmado e falha explícita do timer invalidam a expectativa. O recibo persiste entre aberturas do app.

Testes: `testes/test_pc_control.py` e `PCEnergyReceiptTest`, incluindo comandos recusados, prazo, expiração, persistência, cancelamento e erro real.

## Despertar por Wi-Fi nesta máquina

Investigação em 09/10/2026: adaptador USB 0bda:b812, RTL8822BU, kernel 7.1.13-200.fc44.x86_64. O driver original rtw88_8822bu não anuncia WoWLAN: iw wowlan retorna EOPNOTSUPP. Isso descreve a combinação atual e não comprova incapacidade do adaptador sob Windows/outros drivers.

Foi compilado e instalado para teste o driver RinCat/RTL88x2BU-Linux-Driver, revisão b4e4c1bf0c9866b958b2138504742d0060d9343f, firmware 30.20, com CONFIG_WOWLAN=y e CONFIG_WAKEUP_TYPE=0x1. A compilação manual e a instalação DKMS passaram. O DKMS precisa de 'make' entre aspas em MAKE para não acrescentar KERNELRELEASE à chamada externa e selecionar indevidamente o ramo interno do Makefile.

Verificações: o Wi-Fi reconectou e acessou HTTPS. Um pacote mágico de 102 bytes enviado pelo celular na mesma LAN foi recebido e comparado integralmente no PC ativo. O driver alternativo anuncia apenas WIPHY_WOWLAN_ANY; os gatilhos reais do firmware foram limitados a pacote mágico (rtw_wow_enable=1, rtw_wakeup_event=1).

Três testes reais deep/S3, autorizados pelo usuário, programaram três pacotes do celular após 25 segundos e um fallback RTC após 90 segundos. Todos retornaram após aproximadamente 93 segundos, portanto nenhum comprovou despertar pelo pacote mágico:

1. Driver alternativo padrão: o firmware registrou wakeup_reason=0x21, correspondente a RX_MAGIC_PKT. Recebeu/reconheceu o pacote, mas não acordou o PC antes do RTC.
2. Habilitar temporariamente o despertar do root hub USB3: mesmo resultado. O estado anterior disabled do hub foi restaurado.
3. Ajuste experimental device_init_wakeup também no dispositivo USB principal, além da interface: mesmo tempo de retorno e erros de I/O na retomada. A USB principal anuncia bmAttributes=0x80, sem Remote Wakeup. O ajuste foi rejeitado; não manter nem aplicar automaticamente.

O driver alternativo e sua preferência de carregamento foram retirados após os testes, restaurando o original do Fedora e a configuração anterior de wake-on-wlan do perfil NetworkManager. Alarmes RTC temporários foram removidos. ADB foi reconectado após as suspensões, sem reiniciar aplicativos. A suspensão automática e as configurações de energia da Emily não foram alteradas. Registros técnicos: /var/tmp/emily-wowlan-suspend-test.log, /var/tmp/emily-wowlan-suspend-test2.log, /var/tmp/emily-wowlan-suspend-test3.log e /var/tmp/emily-wowlan-final-restore.log.

Não foi criada ferramenta Android de despertar porque o mecanismo físico ainda não funciona nessa combinação. Isso também exigirá garantir que o pacote alcance a LAN quando o celular estiver fora de casa. Não cortar energia com a tomada inteligente para acordar um PC suspenso: a sessão em RAM seria perdida. A tomada é a solução prevista para ligar após desligamento completo.
