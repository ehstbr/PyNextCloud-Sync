# Termos de Uso

Última atualização: 11 de agosto de 2026

Estes Termos de Uso se aplicam ao PyNextCloud Sync (o “Software”). Ao instalar, executar, copiar, modificar ou distribuir o Software, você declara estar ciente e de acordo com as condições abaixo e com a [Licença Pública Geral GNU versão 3 ou posterior](LICENSE).

## 1. Projeto independente e não oficial

O PyNextCloud Sync é um projeto independente, não oficial e desenvolvido por terceiros. Ele não possui afiliação, patrocínio, endosso, manutenção ou qualquer outro vínculo com a Nextcloud GmbH.

Nextcloud® é marca registrada da Nextcloud GmbH. Nomes, marcas, serviços e softwares de terceiros pertencem aos respectivos titulares. Sua menção serve exclusivamente para indicar compatibilidade ou dependências técnicas.

## 2. A sincronização bidirecional altera dados

O Software realiza sincronização bidirecional entre uma pasta local e uma conta Nextcloud configurada. De acordo com o estado local e remoto, a sincronização pode enviar, receber, renomear, substituir, mesclar, gerar conflitos ou excluir arquivos e pastas.

O PyNextCloud Sync delega a reconciliação e o tratamento de conflitos ao `nextcloudcmd`. O comportamento desse motor, do servidor Nextcloud, armazenamento, rede, provedores de autenticação, proxies reversos e aplicativos opcionais do servidor está fora do controle direto deste projeto.

## 3. Backup e testes são responsabilidade do usuário

Antes do uso regular, teste o Software com dados não críticos em um ambiente sob seu controle. Mantenha backups atuais, independentes e restauráveis de todos os arquivos importantes. Uma cópia sincronizada não constitui, por si só, um backup.

Não direcione mais de um mecanismo de sincronização para a mesma pasta local. Confira as exclusões, pasta local, identidade da conta, espaço disponível, cota do servidor e permissões antes de iniciar a sincronização.

## 4. Uso por sua conta e risco

O Software é fornecido **“no estado em que se encontra” e “conforme disponível”**, sem garantias de qualquer natureza. Seu uso ocorre integralmente por conta e risco do usuário.

No limite máximo permitido pela legislação aplicável, autores, titulares dos direitos autorais, colaboradores e distribuidores não se responsabilizam por perda ou corrupção de dados, exclusões indesejadas, conflitos, transferências incompletas, indisponibilidade, perda de acesso, incidentes de segurança, interrupção de atividades, lucros cessantes ou quaisquer danos diretos, indiretos, incidentais, especiais, exemplares ou consequenciais decorrentes do uso ou da impossibilidade de uso do Software.

Nenhum conteúdo da documentação, interface, logs ou notas de versão constitui garantia de que a sincronização foi concluída corretamente ou de que os dados poderão ser recuperados.

## 5. Compatibilidade e versões futuras

A versão atual foi testada com o [Nextcloud Hub 26 Spring](https://nextcloud.com/) **(34.0.1)** implantado pelo **Nextcloud AIO**.

Não há garantia de funcionamento com todas as edições, instalações, aplicativos, configurações de autenticação, ambientes desktop, distribuições Linux, versões do `nextcloudcmd` ou versões futuras do Nextcloud. Alterações nos projetos externos podem prejudicar ou interromper recursos sem aviso prévio.

## 6. Segurança e credenciais

Os segredos da conta são solicitados e armazenados pelo Secret Service do desktop quando disponível. O usuário continua responsável por proteger o computador, carteira de senhas, conta Nextcloud, senhas de aplicativo, servidor, rede, backups e métodos de recuperação.

Permitir certificados TLS inválidos ou autoassinados reduz a segurança da conexão e deve ser ativado somente para um servidor compreendido e considerado confiável pelo usuário.

## 7. Privacidade

O Software não contém telemetria, analytics, publicidade ou envio remoto de relatórios de falha. Configurações e logs são armazenados localmente. Valores sensíveis são ocultados das mensagens geradas pelo aplicativo na medida do possível, mas o usuário ainda deve revisar as informações de diagnóstico antes de compartilhá-las publicamente.

## 8. Softwares e serviços de terceiros

O PyNextCloud Sync depende de softwares e protocolos mantidos separadamente por terceiros. Cada componente permanece sujeito à sua própria licença e aos seus próprios termos. Consulte [THIRD-PARTY.pt-BR.md](THIRD-PARTY.pt-BR.md) para conhecer os principais projetos utilizados ou suportados.

O uso de um servidor Nextcloud também pode estar sujeito a termos, políticas de privacidade, cotas e regras operacionais estabelecidas pelo proprietário ou provedor de hospedagem.

## 9. Licença

O PyNextCloud Sync versão `0.1.19` e as versões posteriores são distribuídos sob a [Licença Pública Geral GNU versão 3 ou posterior](LICENSE). Suas cláusulas sobre ausência de garantia e limitação de responsabilidade permanecem integralmente aplicáveis. As dependências externas não são relicenciadas por este projeto, e as versões anteriores do PyNextCloud Sync permanecem disponíveis sob a licença incluída em cada lançamento correspondente.

## 10. Alterações destes termos

Estes termos podem ser atualizados em versões futuras. O documento incluído em uma determinada versão rege aquela cópia do Software, observada a legislação aplicável.
