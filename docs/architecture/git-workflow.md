# Git delivery boundary
The agent never receives Git credentials or authoritative Git metadata. Discovery reads a protected local bare mirror without checkout hooks/filters. Implemented files become a candidate manifest; trusted broker code constructs an index from those exact bytes and modes, writes a tree, and creates a deterministic commit parented by the approved base.

Delivery rechecks current approval, candidate evidence, scope and the remote base. A run/attempt-specific branch is used. Existing different branch content or unrelated PR ownership markers block delivery. Push does not use force, merge or default-branch updates.

Trusted Git receives its scoped HTTPS authentication header only in its private process environment, with an explicit empty inherited environment, disabled hooks/proxy/redirects and pinned resolution. It does not run repository code. [Git documents http.curloptResolve and the related HTTP settings](https://git-scm.com/docs/git-config#Documentation/git-config.txt-httpcurloptResolve); the actual installed Git/libcurl behavior still requires qualification.

GitHub/Gitea PR adapters use pinned API transports, bounded pagination and ownership markers. The PR body contains candidate/approval identity and a safe summary. Root-only intent journals distinguish prepared/push/PR/completed phases. Ambiguous writes stop for human reconciliation; a completed journal can repair a missing database completion. See upgrade-and-recovery.md.

Current authoring policy allows local Git only. No remote was contacted and no commit was created. Real PR tests remain deferred to a separately permitted environment.
