<div align="center">
  <img src="data/icons/com.eduhcommerce.PyNextCloudSync.svg" width="112" alt="Ícone do PyNextCloud Sync">
  <h1>PyNextCloud Sync</h1>
  <p><strong>Seus arquivos, localmente. Seu Nextcloud, sincronizado.</strong></p>
  <p>Um aplicativo leve e integrado ao GNOME para manter no Linux uma cópia física completa de uma conta Nextcloud.</p>
  <p>
    <a href="README.md">English</a>
    ·
    <a href="https://eduhcommerce.com.br">Site</a>
    ·
    <a href="https://github.com/ehstbr/PyNextCloud-Sync/releases">Versões</a>
    ·
    <a href="https://github.com/ehstbr/PyNextCloud-Sync/issues">Relatar um problema</a>
  </p>
  <p>
    <img src="https://img.shields.io/badge/versão-0.1.32-6557e8?style=flat-square" alt="Versão 0.1.32">
    <img src="https://img.shields.io/badge/plataforma-Linux-f0c674?style=flat-square&logo=linux&logoColor=111" alt="Linux">
    <img src="https://img.shields.io/badge/desktop-GNOME-4a86cf?style=flat-square&logo=gnome&logoColor=white" alt="GNOME">
    <img src="https://img.shields.io/badge/GTK-4-4a86cf?style=flat-square&logo=gtk&logoColor=white" alt="GTK 4">
    <img src="https://img.shields.io/badge/licença-GPLv3%2B-2da44e?style=flat-square" alt="GNU GPLv3 ou posterior">
  </p>
</div>

<p align="center">
  <img src="docs/screenshots/main-window.png" width="820" alt="Janela principal do PyNextCloud Sync durante a sincronização">
</p>

## Um aplicativo pequeno com uma função muito clara

O PyNextCloud Sync mantém **uma conta Nextcloud** espelhada em **uma pasta local**. Ele evita intencionalmente sincronização seletiva, arquivos virtuais, várias árvores de contas, painéis de métricas e recursos sem relação direta com a sincronização.

A reconciliação bidirecional é realizada pelo motor oficial [`nextcloudcmd`](https://github.com/nextcloud/desktop). O PyNextCloud Sync acrescenta a experiência de desktop: login seguro, gatilhos automáticos, janela compacta de estado, integração com o GNOME, logs e menu na bandeja.

### Destaques

- **Espelho físico completo:** todos os arquivos elegíveis da conta permanecem disponíveis localmente.
- **Motor oficial de sincronização:** sem algoritmo WebDAV próprio para reconciliar arquivos.
- **Interface nativa do GNOME:** GTK 4 e Libadwaita, com layout compacto e familiar.
- **Login seguro:** Nextcloud Login Flow v2 ou credenciais manuais armazenadas pelo Secret Service / GNOME Keyring.
- **Autorização identificada por computador:** nomes estáveis, reconexão sem reconfigurar a conta e uma página própria com informações da conta.
- **Uso do armazenamento visível:** a tela inicial mostra a ocupação da cota ou o estado ilimitado pelo espaço disponível no servidor.
- **Detecção local rápida:** monitoramento recursivo com `inotify` e agrupamento de eventos.
- **Detecção de mudanças remotas:** `notify_push` opcional com intervalo de segurança configurável.
- **Operação discreta:** uma fila que agrupa solicitações e no máximo um processo `nextcloudcmd`.
- **Inicialização protegida:** antes do modo bidirecional, uma pasta temporária nova obtém a árvore do servidor e o usuário revisa como os dois lados serão unidos.
- **Trava contra exclusões anormais:** pasta ausente, trocada, vazia, ilegível ou com redução acima dos limites bloqueia o motor antes que o Nextcloud seja alterado.
- **Integração útil com o desktop:** favorito no Arquivos, atalho na Área de Trabalho, ícone especial da pasta, inicialização automática, notificações e controles na bandeja.
- **Privacidade por princípio:** sem telemetria, analytics, publicidade ou envio remoto de falhas.
- **Multilíngue:** interface-base em inglês, com traduções para português do Brasil e espanhol.

## Capturas de tela

<table>
  <tr>
    <td width="50%" align="center"><strong>Configurações integradas ao GNOME</strong><br><img src="docs/screenshots/settings-general.png" alt="Configurações gerais"></td>
    <td width="50%" align="center"><strong>Gatilhos independentes</strong><br><img src="docs/screenshots/settings-sync.png" alt="Configurações de sincronização"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><strong>Controles de rede</strong><br><img src="docs/screenshots/settings-network.png" alt="Configurações de rede"></td>
    <td width="50%" align="center"><strong>Logs locais e diagnóstico</strong><br><img src="docs/screenshots/settings-advanced.png" alt="Configurações avançadas"></td>
  </tr>
  <tr>
    <td width="50%" align="center"><strong>Atualização opcional</strong><br><img src="docs/screenshots/update-optional.png" alt="Nova atualização opcional disponível"></td>
    <td width="50%" align="center"><strong>Atualização obrigatória</strong><br><img src="docs/screenshots/update-mandatory.png" alt="Nova atualização obrigatória disponível"></td>
  </tr>
</table>

<p align="center">
  <strong>As ações importantes também estão disponíveis na bandeja</strong><br><br>
  <img src="docs/screenshots/tray-menu.png" width="368" alt="Menu de bandeja do PyNextCloud Sync">
</p>

<details>
<summary><strong>Ver a configuração inicial</strong></summary>
<br>
<table>
  <tr>
    <td width="50%"><img src="docs/screenshots/welcome.png" alt="Tela de boas-vindas"></td>
    <td width="50%"><img src="docs/screenshots/connect.png" alt="Endereço do servidor Nextcloud"></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/sign-in.png" alt="Formas de entrar"></td>
    <td width="50%"><img src="docs/screenshots/browser-sign-in.png" alt="Aguardando autorização no navegador"></td>
  </tr>
  <tr>
    <td width="50%"><img src="docs/screenshots/local-folder.png" alt="Seleção da pasta local"></td>
    <td width="50%"><img src="docs/screenshots/review.png" alt="Revisão da configuração"></td>
  </tr>
</table>
</details>

## Como a sincronização funciona

Cada gatilho solicita uma reconciliação bidirecional ao mesmo agendador. Solicitações próximas são agrupadas e o aplicativo nunca inicia intencionalmente dois processos `nextcloudcmd` para a mesma conta.

```mermaid
flowchart LR
    A["Mudanças locais<br>inotify / intervalo"] --> Q["Fila única de<br>sincronização"]
    B["Sinais remotos<br>notify_push / intervalo"] --> Q
    C["Ação manual<br>rede / retomada"] --> Q
    Q --> N["nextcloudcmd"]
    N <--> F["Espelho local"]
    N <--> S["Servidor Nextcloud"]
```

O `notify_push` apenas sinaliza que pode existir uma alteração. Descoberta de arquivos, transferência, conflitos e propagação de exclusões continuam sob responsabilidade do `nextcloudcmd`.

> [!IMPORTANT]
> A sincronização é bidirecional. Alterações locais e remotas — inclusive exclusões — podem ser propagadas para o outro lado. Mantenha backup independente dos dados importantes e não execute outro sincronizador sobre a mesma pasta local.

## Instalação

### Pacote Debian — recomendado

Baixe o `.deb` na [versão mais recente](https://github.com/ehstbr/PyNextCloud-Sync/releases/latest) e instale com o APT para resolver automaticamente os pacotes de sistema necessários:

```bash
cd ~/Downloads
sudo apt update
sudo apt install ./pynextcloud-sync_0.1.32_all.deb
```

Durante uma atualização interativa iniciada com `sudo apt install`, o pacote solicita que uma instância aberta do PyNextCloud Sync seja encerrada normalmente, aguarda a sincronização atual terminar e reinicia o aplicativo atualizado na mesma sessão gráfica. O processo de sincronização nunca é encerrado à força. Atualizações automáticas ou instalações sem uma sessão gráfica identificável deixam o controle do processo para o usuário ou administrador do sistema.

O pacote depende de `nextcloud-desktop-cmd`, Python 3, GTK 4, Libadwaita, PyGObject, libsoup, libsecret, GdkPixbuf e GNOME Keyring. No GNOME, o ícone de bandeja normalmente exige uma extensão AppIndicator/StatusNotifier; a sincronização continua funcionando quando não existe um host de bandeja.

### ZIP do código-fonte

Instale primeiro as dependências:

```bash
sudo apt update
sudo apt install \
  python3 python3-gi \
  gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-gdkpixbuf-2.0 \
  gir1.2-soup-3.0 gir1.2-secret-1 \
  nextcloud-desktop-cmd
```

Depois, extraia e execute:

```bash
unzip PyNextCloud-Sync-0.1.32.zip
cd PyNextCloud-Sync-0.1.32
./run.sh
```

O `run.sh` utiliza o Python e os pacotes GI da distribuição. Ele não cria ambiente virtual nem baixa pacotes da internet.

## Primeira configuração

1. Digite a URL-base usada normalmente para abrir seu Nextcloud.
2. Prefira **Entrar pelo navegador**, com suporte ao Login Flow v2 e autenticação em dois fatores. Também existe login manual com usuário e senha/senha de aplicativo.
3. Escolha a pasta do espelho local. O padrão é `$HOME/NextCloud`.
4. Revise a configuração e inicie a análise protegida.
5. Confira arquivos exclusivos de cada lado, itens iguais, conflitos e bancos de sincronização antigos.
6. Escolha entre mesclar preservando as duas versões, priorizar o Nextcloud, priorizar o computador ou decidir cada conflito individualmente.

Durante a análise, o aplicativo usa uma pasta privada completamente nova para obter uma cópia protegida do servidor. Um banco `.sync_*.db` presente na pasta escolhida é identificado e arquivado fora da árvore sincronizada; ele nunca é reaproveitado silenciosamente. O modo bidirecional, o `inotify`, os temporizadores e o `notify_push` só são ativados depois que o resultado revisado é aplicado, verificado e registrado como base segura.

Uma nova conta então ativa o monitoramento local, intervalo remoto de segurança de 10 minutos, push compatível, exclusões de arquivos descartáveis e inicialização automática. O aplicativo também adiciona a pasta à lateral do Arquivos, cria um link simbólico seguro na Área de Trabalho definida pelo XDG e aplica o ícone próprio. Essas integrações podem ser alteradas separadamente em **Configurações → Geral → Pasta local**.

Instalações atualizadas da `0.1.13` também começam pausadas e passam por essa análise uma vez. Isso é intencional: a versão nova não considera seguro um estado antigo que ainda não possui manifesto próprio.

## Gerenciamento da conta e da autorização

O login pelo navegador identifica novas autorizações no Nextcloud como `PyNextCloud-Sync (nome-do-computador)`. Assim, computadores diferentes podem ser reconhecidos sem vincular o nome da autorização à versão instalada do aplicativo.

**Configurações → Conta** reúne a identidade configurada, pasta local, nome registrado da autorização, nome de exibição, e-mail, cota de armazenamento e informações básicas do servidor. Se uma senha de aplicativo for revogada, **Reconectar conta** renova somente a autorização. A pasta local, as preferências de sincronização e a base de segurança existente não são reiniciadas. A nova credencial é verificada antes da retomada de uma sincronização normal protegida.

A tela inicial mostra o último uso de armazenamento salvo com uma barra proporcional e a porcentagem centralizada quando a conta possui uma cota definida. Contas sem cota definida usam uma barra estática vazia com o símbolo de infinito e informam o espaço ocupado, deixando claro que o limite prático é o armazenamento disponível no servidor. Abrir a Home ou as Configurações não provoca outra consulta: os dados salvos aparecem imediatamente. A identidade da conta e as informações básicas do servidor são atualizadas uma vez quando o processo do aplicativo inicia, enquanto a ocupação da cota é atualizada novamente após cada sincronização bem-sucedida. **Configurações → Conta → Atualizar informações da conta** continua disponível para uma atualização manual explícita.

## Proteção contínua contra exclusões

Depois de cada sincronização bem-sucedida, o PyNextCloud Sync registra um manifesto local da árvore verificada. Antes de executar novamente o motor bidirecional, ele confere a identidade e o conteúdo básico da pasta.

A sincronização é bloqueada quando:

- a pasta local desaparece, deixa de ser uma pasta ou não pode ser lida;
- a pasta configurada parece ter sido substituída ou remontada;
- uma pasta anteriormente preenchida aparece vazia;
- o banco de estado do `nextcloudcmd` desaparece inesperadamente;
- somem pelo menos 10 arquivos ou 20% da base anterior, conforme os limites configuráveis.

Na revisão de segurança, o usuário pode restaurar o conteúdo a partir do Nextcloud, manter tudo pausado ou aprovar intencionalmente aquelas exclusões uma única vez. Uma notificação urgente do GNOME chama atenção para o bloqueio, e a ação **Revisar agora** abre diretamente a confirmação. Os limites ficam em **Configurações → Avançado → Trava de segurança contra exclusões**. Pasta vazia, ausente, substituída ou ilegível sempre exige revisão, independentemente desses limites.

Essa trava cobre deliberadamente as alterações locais antes que possam ser propagadas ao Nextcloud. Exclusões originadas no servidor ou em outro computador sincronizado continuam sendo aplicadas localmente pelo `nextcloudcmd` sem essa confirmação.

Se o favorito for removido pelo Arquivos, o aplicativo respeita a escolha e reflete o estado real, sem recriá-lo.

## Verificação de atualizações

A cada inicialização, o PyNextCloud Sync consulta o `version.json` na raiz do
repositório do GitHub antes de ativar o mecanismo de sincronização. GitHub
indisponível, falha HTTP ou manifesto inválido são registrados no log e não
impedem a inicialização normal.

| Campo | Finalidade |
| --- | --- |
| `schema_version` | Versão do contrato do manifesto |
| `version` | Versão mais recente conforme SemVer |
| `mandatory` | Impede versões anteriores de funcionar quando `true` |
| `released_at` | Data e hora do lançamento em ISO 8601 e UTC |
| `summary` | Resumo curto da versão em texto puro |
| `changelog` | Lista completa e ordenada de alterações em texto puro |

Atualizações opcionais usam uma janela Libadwaita não modal, permitindo que a
inicialização normal continue. Atualizações obrigatórias mantêm desativados o
mecanismo, o monitoramento de arquivos, os temporizadores e a conexão push,
oferecendo somente a página oficial de releases ou o fechamento do aplicativo.
A mesma validação pode ser iniciada manualmente em **Sobre → Verificar
atualização**. O changelog detalhado permanece recolhido até ser solicitado.

## Organização das configurações

| Área | O que controla |
| --- | --- |
| Geral | Inicialização automática, bateria, pasta local, favorito no Arquivos, atalho na Área de Trabalho e ícone especial |
| Sincronização | `inotify`, intervalo local, `notify_push`, intervalo remoto de segurança e exclusões de arquivos descartáveis |
| Rede | Remoção da conta, proxy HTTP opcional e permissão explícita para certificados inválidos ou autoassinados |
| Avançado | Logs diários, retenção, saída detalhada, limites da trava de exclusões e diagnóstico do runtime |

Os quatro gatilhos automáticos podem ser combinados ou desativados. Com monitoramento local, intervalo local, push e intervalo remoto desligados, o aplicativo funciona somente por sincronização manual.

## Compatibilidade

Atualmente testado com o [**Nextcloud Hub 26 Spring**](https://nextcloud.com/) **(34.0.1)** implantado pelo **Nextcloud AIO**.

A compatibilidade com outras instalações pode depender da versão do `nextcloudcmd`, configuração do servidor, proxy reverso, método de autenticação e aplicativos opcionais. Não há garantia de compatibilidade com versões futuras do Nextcloud.

## Exclusões

As regras-padrão abrangem arquivos descartáveis conservadores como `.DS_Store`, `Thumbs.db`, travas de suítes de escritório, swaps do Vim, sufixos de backup e o arquivo de ruído do diário do `nextcloudcmd`. Arquivos ocultos do usuário continuam elegíveis para sincronização porque o cliente sempre é executado com suporte a ocultos.

Padrões contendo `/`, `\` ou `..` são rejeitados. A versão 1 não permite excluir pastas, caminhos ou subárvores remotas.

## Arquivos, credenciais e privacidade

- Configuração: `$XDG_CONFIG_HOME/pynextcloud-sync/settings.json`
- Exclusões geradas: `$XDG_CONFIG_HOME/pynextcloud-sync/excludes.lst`
- Logs diários: `$XDG_STATE_HOME/pynextcloud-sync/pynextcloud-sync-YYYY-MM-DD.log`
- Manifesto de segurança: `$XDG_STATE_HOME/pynextcloud-sync/safety-manifest.json`
- Bancos antigos arquivados: `$XDG_STATE_HOME/pynextcloud-sync/safety-archives/`
- Segredo da conta: GNOME Keyring ou outro provedor compatível com Secret Service

Os logs permanecem no computador, usam um arquivo por dia e são mantidos por 30 dias por padrão. Valores sensíveis são ocultados das mensagens de log geradas pelo aplicativo. Se o login biométrico deixar a carteira `Login` bloqueada, o GNOME exibe sua solicitação nativa de desbloqueio antes da sincronização. A senha do computador é tratada somente pelo GNOME; o PyNextCloud Sync não a recebe nem armazena. Cancelar a solicitação deixa o aplicativo aguardando o comando explícito **Desbloquear carteira de senhas**, sem repetir diálogos ou acusar credenciais inválidas do Nextcloud.

## Desenvolvimento e testes

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

A suíte em Python puro inclui um `nextcloudcmd` simulado para cenários de sucesso, falha, erro de autenticação, saída e execução lenta. Testes com conta real, host de bandeja do GNOME, UPower, suspensão/retomada e memória de longa duração ainda exigem uma sessão desktop real.

Contribuições são bem-vindas quando preservam o escopo enxuto, baixo consumo ocioso, tratamento seguro de credenciais e design orientado ao GNOME. Consulte [CONTRIBUTING.md](CONTRIBUTING.md).

## Documentação

- [Histórico de alterações](CHANGELOG.md)
- [Termos de Uso em português](TERMS.pt-BR.md)
- [Licença Pública Geral GNU v3 ou posterior](LICENSE)
- [Projetos de terceiros e licenças](THIRD-PARTY.pt-BR.md)
- [Como contribuir](CONTRIBUTING.md)

## Estado do projeto

A versão `0.1.32` é uma versão de desenvolvimento destinada à avaliação. Teste primeiro com dados não críticos e mantenha sempre backups independentes dos arquivos importantes.

---

<p align="center"><sub>
Nextcloud® é marca registrada da Nextcloud GmbH. O PyNextCloud Sync é um projeto independente e não oficial, sem afiliação, patrocínio, endosso ou qualquer outro vínculo com a Nextcloud GmbH. O uso está sujeito aos <a href="TERMS.pt-BR.md">Termos de Uso</a> e à Licença Pública Geral GNU versão 3 ou posterior.
</sub></p>
