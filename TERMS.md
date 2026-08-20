# Terms of Use

Last updated: August 11, 2026

These Terms of Use apply to PyNextCloud Sync (the “Software”). By installing, running, copying, modifying, or distributing the Software, you acknowledge and accept the conditions below together with the [GNU General Public License version 3 or later](LICENSE).

## 1. Independent and unofficial project

PyNextCloud Sync is an independent, unofficial third-party project. It is not affiliated with, sponsored by, endorsed by, maintained by, or otherwise connected to Nextcloud GmbH.

Nextcloud® is a registered trademark of Nextcloud GmbH. All third-party names, trademarks, services, and software remain the property of their respective owners. Their mention identifies compatibility or technical dependencies only.

## 2. Bidirectional synchronization changes data

The Software performs bidirectional synchronization between a local folder and a configured Nextcloud account. Depending on local and remote state, synchronization may upload, download, rename, replace, merge, conflict, or delete files and folders.

PyNextCloud Sync delegates reconciliation and conflict handling to `nextcloudcmd`. The behavior of that engine, the Nextcloud server, storage, network, authentication providers, reverse proxies, and optional server apps is outside the direct control of this project.

## 3. Backups and testing are the user's responsibility

Before regular use, test the Software with non-critical data in an environment you control. Maintain current, independent, and restorable backups of every important file. A synchronized copy is not, by itself, a backup.

Do not point more than one synchronization engine at the same local folder. Review exclusions, local folder selection, account identity, available disk space, server quota, and permissions before starting synchronization.

## 4. Use at your own risk

The Software is provided **“as is” and “as available”**, without warranties or guarantees of any kind. You use it entirely at your own risk.

To the maximum extent permitted by applicable law, the authors, copyright holders, contributors, and distributors are not responsible or liable for data loss, data corruption, unintended deletion, conflicts, incomplete transfers, downtime, loss of access, security incidents, business interruption, lost profits, or any direct, indirect, incidental, special, exemplary, or consequential damage arising from use of or inability to use the Software.

Nothing in the documentation, interface, logs, or release notes constitutes a guarantee that synchronization completed correctly or that data can be recovered.

## 5. Compatibility and future versions

The current release has been tested with [Nextcloud Hub 26 Spring](https://nextcloud.com/) **(34.0.1)** deployed with **Nextcloud AIO**.

No guarantee is made that the Software works with every Nextcloud edition, deployment, app, authentication configuration, desktop environment, Linux distribution, `nextcloudcmd` version, or future Nextcloud release. Upstream changes may partially or completely break features without prior notice.

## 6. Security and credentials

Account secrets are requested from and stored through the desktop Secret Service when available. Users remain responsible for securing their computer, keyring, Nextcloud account, app passwords, server, network, backups, and recovery methods.

Allowing invalid or self-signed TLS certificates reduces connection security and should be enabled only for a server the user understands and trusts.

## 7. Privacy

The Software does not include telemetry, analytics, advertising, or remote crash reporting. Configuration and logs are stored locally. Sensitive values are redacted from application-owned messages on a best-effort basis, but users should still review diagnostic information before sharing it publicly.

## 8. Third-party software and services

PyNextCloud Sync depends on separately maintained third-party software and protocols. Each component remains subject to its own license and terms. See [THIRD-PARTY.md](THIRD-PARTY.md) for the principal projects used or supported.

Use of a Nextcloud server may also be subject to terms, privacy policies, quotas, and operational rules established by the server owner or hosting provider.

## 9. License

PyNextCloud Sync version `0.1.19` and subsequent releases are distributed under the [GNU General Public License version 3 or later](LICENSE). Its warranty and liability disclaimer remains fully applicable. External dependencies are not relicensed by this project, and earlier PyNextCloud Sync releases remain available under the license distributed with each respective release.

## 10. Changes to these terms

These terms may be updated in future releases. The version bundled with a particular release governs that copy of the Software, subject to applicable law.
