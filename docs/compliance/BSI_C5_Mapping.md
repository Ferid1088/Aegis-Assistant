# BSI IT-Grundschutz / C5 Kontrollzuordnung

*(BSI IT-Grundschutz / C5 Control Mapping)*

> **Entwurf — vor Verwendung durch einen Rechtsanwalt/Datenschutzbeauftragten
> zu prüfen.** Insbesondere die Einordnung als Auftragsverarbeiter/
> Verantwortlicher (siehe `TOM.md`) bedarf rechtlicher Bestätigung.
>
> (Draft — must be reviewed by a lawyer/data protection officer before
> real use. In particular, the controller/processor classification
> requires legal confirmation.)

## Geltungsbereich dieser Zuordnung

Diese Zuordnung deckt ausschließlich die C5/IT-Grundschutz-Domänen ab, die
von den **Kontrollen dieser Software selbst** berührt werden. Domänen, die
in die Verantwortung des Hosting-Anbieters oder des Kunden (physische
Sicherheit des Rechenzentrums, Personalsicherheit, organisatorische
Richtlinien des Kunden) fallen, sind hier bewusst **nicht** aufgeführt —
eine Software-Appliance kann diese nicht selbst erfüllen.

## IDM — Identitäts- und Berechtigungsmanagement (Identity and Access Management)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Rollenbasierte Zugriffskontrolle | `rag/crosscutting/security/` — granulare Berechtigungsprüfung pro Endpunkt |
| Mehr-Faktor-Authentifizierung | Verfügbar (TOTP), opt-in pro Benutzer — derzeit keine erzwungene organisationsweite Richtlinie (`rag/auth/mfa.py`) |
| Sitzungs-Widerruf | Entzogene Berechtigungen wirken sich auf die nächste Anfrage aus |

## KRY — Kryptografie und Schlüsselmanagement (Cryptography and Key Management)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Verschlüsselung von Geheimnissen, Schlüsseln und Backup-Archiven | Envelope-Encryption-Keystore (`rag/crosscutting/security/keystore.py`); Backup-Archive werden mit einem Keystore-Schlüssel verschlüsselt (`rag/backup/archive.py`). **Nicht abgedeckt:** Konversationsinhalte selbst (`question`/`answer`/`citations`) werden als Klartext in der Datenbank gespeichert, siehe `Loeschkonzept.md`. |
| Verschlüsselung während der Übertragung | TLS-Terminierung via nginx-Reverse-Proxy (`nginx/nginx.conf`), automatische Zertifikatserzeugung bei Installation (`rag/bootstrap/tls_cert.py`) |
| Schlüsselvernichtung, vorbereitet für ein zukünftiges Crypto-Shred-Verfahren | Ein pro-Konversation-Schlüssel wird bei einer Löschanfrage vernichtet, verschlüsselt aber **aktuell keinen Konversationsinhalt** — die tatsächliche, heute wirksame Löschung erfolgt über einen harten Datenbank-Löschvorgang, nicht über diesen Schlüssel. Details siehe `Loeschkonzept.md`. |

## LOG — Protokollierung und Überwachung (Logging and Monitoring)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Manipulationssicheres Audit-Log | Hash-verkettetes Log mit Erkennung nachträglicher Änderungen (`rag/crosscutting/security/audit.py`) |
| Systemmetriken und Alarmierung | Prometheus/Grafana-Stack mit Alarmregeln (z. B. geringer Speicherplatz), strukturiertes JSON-Logging |
| Fehlerverfolgung | Selbst-gehostetes Fehler-Tracking (GlitchTip) |

## BEI — Betriebskontinuität und Notfallmanagement (Backup and Recovery)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Verschlüsseltes Backup | Keystore-gesicherte Archive (`rag/backup/`) |
| Getestetes Restore-Verfahren | Tatsächlich end-to-end getestet, nicht nur angenommen (Integrationstests) |
| Ressourcenbegrenzung gegen Erschöpfung durch einzelne Nutzer | Pro-Nutzer-Rate-Limits auf Upload/Chat mit kontrolliertem Fail-Open bei Redis-Ausfall (`rag/crosscutting/security/rate_limit.py`), Pro-Nutzer-Obergrenze für gleichzeitige Ingestions-Aufträge (`rag/crosscutting/security/ingestion_limits.py`) |

**Bekannte Lücke:** ein automatischer Container-Neustart bei Ausfall
(Docker-Compose-Neustartrichtlinien bzw. Healthchecks) ist in
`docker-compose.yml` derzeit **nicht konfiguriert** — kein Service trägt
eine `restart:`-Richtlinie oder einen `healthcheck:`-Block. Ein
ausgefallener Container wird heute nicht automatisch neu gestartet.

## OPS — Systemhärtung und Netzwerksicherheit (System & Network Hardening)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Nicht-Root-Container | Container laufen als dedizierter Nicht-Root-Benutzer (`Dockerfile`) |
| Schreibgeschütztes Root-Dateisystem, keine zusätzlichen Capabilities | `read_only: true`, `cap_drop: ["ALL"]` für `app`/`worker` (`docker-compose.yml`) |
| Netzwerksegmentierung | Datenbank-Ports (Postgres, Redis, Neo4j) sind nicht auf dem Host veröffentlicht — nur der TLS-Reverse-Proxy ist erreichbar (`docker-compose.yml`) |
| Schema-/Migrationsversionierung | Versionierte, pro Migration einzeln committete Datenbank- und Vektorspeicher-Migrationen (`rag/migrations/`) |

## PSS / SWD — Patch- und Schwachstellenmanagement (Patch and Vulnerability Management)

| Kontrolle | Umsetzung in dieser Anwendung |
|---|---|
| Container-Image-Schwachstellenscans | Trivy-Scan bei jedem Merge in der CI-Pipeline, hartes Ausschlusskriterium für CRITICAL-Schwachstellen (`.github/workflows/ci.yml`) |
| Reproduzierbare, versionsgesperrte Abhängigkeiten | `uv.lock` |
| Signierte Update-Bundles | Ed25519-signierte Offline-Update-Bundles, Signaturprüfung vor Installation |

## Außerhalb des Geltungsbereichs dieser Software (Out of Scope)

Diese Domänen sind für ein produktives BSI-C5/Grundschutz-Audit relevant,
liegen jedoch außerhalb dessen, was eine Software-Appliance selbst
kontrollieren kann:

- **Physische Sicherheit** des Rechenzentrums/Serverraums — Verantwortung
  des Kunden bzw. des Hosting-Anbieters.
- **Personalsicherheit** (Background-Checks, Vertraulichkeitsvereinbarungen
  für Mitarbeitende des Kunden) — Verantwortung des Kunden.
- **Organisatorische Richtlinien** (interne Prozesse, Schulungen) —
  Verantwortung des Kunden als Betreiber der Appliance.
