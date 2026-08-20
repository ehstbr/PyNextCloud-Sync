# Projetos de terceiros e licenças

O PyNextCloud Sync é um software original distribuído sob a [Licença Pública Geral GNU versão 3 ou posterior](LICENSE). Seu funcionamento utiliza pacotes de sistema, protocolos e projetos independentes relacionados abaixo.

O ZIP do código-fonte **não** incorpora o código nem os binários dessas dependências de execução. O pacote Debian as declara como dependências ou recomendações, e o gerenciador de pacotes do sistema operacional faz a instalação separadamente. Cada componente externo continua sujeito à respectiva licença; este repositório não o relicencia.

Os identificadores abaixo resumem a principal licença informada pelo projeto original. Consulte o projeto vinculado e os arquivos de copyright fornecidos pela sua distribuição Linux para conhecer os termos completos da versão instalada.

## Componentes principais de execução

| Projeto | Como o PyNextCloud Sync utiliza | Licença do projeto original |
| --- | --- | --- |
| [Nextcloud Desktop Client / `nextcloudcmd`](https://github.com/nextcloud/desktop) | Descoberta de arquivos, reconciliação bidirecional, transferências, conflitos e propagação de exclusões | GPL-2.0-or-later |
| [Python](https://www.python.org/) | Ambiente de execução do aplicativo | Python Software Foundation License |
| [PyGObject](https://github.com/GNOME/pygobject) | Bindings Python para bibliotecas GObject Introspection | LGPL-2.1-or-later |
| [GTK 4](https://github.com/GNOME/gtk) | Toolkit da interface gráfica | LGPL-2.1-or-later |
| [Libadwaita](https://github.com/GNOME/libadwaita) | Padrões de aplicativos GNOME e widgets adaptáveis | LGPL-2.1-or-later |
| [GLib / GObject / GIO](https://github.com/GNOME/glib) | Loop principal, D-Bus, monitoramento de arquivos, integração de rede, utilitários e serviços do desktop | LGPL-2.1-or-later |
| [libsoup](https://github.com/GNOME/libsoup) | Requisições HTTPS e conexão WebSocket para APIs do Nextcloud e sinais de push | LGPL-2.1-or-later |
| [libsecret](https://github.com/GNOME/libsecret) | Acesso ao Secret Service para credenciais da conta | LGPL-2.1-or-later |
| [GdkPixbuf](https://github.com/GNOME/gdk-pixbuf) | Tratamento das imagens do aplicativo e da bandeja | LGPL-2.1-or-later |
| [GNOME Keyring](https://github.com/GNOME/gnome-keyring) | Provedor de Secret Service recomendado no GNOME | Componentes GPL-2.0 e LGPL-2.1; consulte os arquivos do projeto |

## Integrações opcionais

| Projeto | Relação | Licença do projeto original |
| --- | --- | --- |
| [Nextcloud Client Push (`notify_push`)](https://github.com/nextcloud/notify_push) | Aplicativo opcional no servidor, utilizado apenas para sinais remotos de melhor esforço; não é incorporado nem instalado pelo PyNextCloud Sync | AGPL-3.0 |
| [Extensão AppIndicator/KStatusNotifierItem do GNOME Shell](https://github.com/ubuntu/gnome-shell-extension-appindicator) | Host opcional da bandeja recomendado no GNOME; não é incorporado | GPL-2.0 |

O PyNextCloud Sync implementa diretamente as interfaces freedesktop StatusNotifierItem e menu D-Bus por meio do GIO. Ele não inclui nem vincula a `libappindicator`.

## Ferramentas de build e tradução

Os metadados e o processo de lançamento também oferecem suporte a [Meson](https://github.com/mesonbuild/meson), [setuptools](https://github.com/pypa/setuptools), [GNU gettext](https://www.gnu.org/software/gettext/) e às ferramentas de empacotamento Debian. Essas ferramentas são executadas durante o desenvolvimento ou a montagem dos pacotes e não são incorporadas ao código do aplicativo.

## Marcas e independência

Nextcloud® é marca registrada da Nextcloud GmbH. GNOME e outros nomes podem ser marcas dos respectivos titulares.

O PyNextCloud Sync é independente e não oficial. A presença de um projeto nesta lista representa atribuição e informação de compatibilidade, não afiliação, patrocínio, certificação ou endosso.
