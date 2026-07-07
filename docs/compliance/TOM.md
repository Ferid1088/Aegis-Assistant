# Technische und Organisatorische Maßnahmen (TOM)

*(Technical and Organizational Measures, Art. 32 DSGVO)*

> **Entwurf — vor Verwendung durch einen Rechtsanwalt/Datenschutzbeauftragten
> zu prüfen.** Insbesondere die Einordnung als Auftragsverarbeiter/
> Verantwortlicher (siehe unten) bedarf rechtlicher Bestätigung.
>
> (Draft — must be reviewed by a lawyer/data protection officer before
> real use. In particular, the controller/processor classification
> requires legal confirmation.)

## Einordnung: Verantwortlicher oder Auftragsverarbeiter?

Diese Anwendung wird als vollständig air-gapped, on-premises betriebene
Appliance ausgeliefert: alle Daten verbleiben auf dem Server des Kunden,
der Hersteller hat keinen technischen Zugriff auf Kundendaten im laufenden
Betrieb. Daraus folgt regelmäßig, dass der **Kunde Verantwortlicher** im
Sinne der DSGVO ist und der Hersteller **kein Auftragsverarbeiter**, da
keine Verarbeitung "im Auftrag" des Kunden stattfindet, auf die der
Hersteller Zugriff hätte.

**Ausnahme:** Sofern der Hersteller Fernwartung, Remote-Support oder
Remote-Updates anbietet, die auf Kundendaten zugreifen könnten, ändert sich
diese Einordnung. Das Support-Modell muss in diesem Fall gesondert
definiert und dokumentiert werden.

*(This appliance ships fully air-gapped and on-premises: all data stays on
the customer's own server, and the vendor has no runtime access to
customer data. This typically means the customer is the DSGVO controller
and the vendor is not a processor at all — a stronger posture than a SaaS
product. Exception: if the vendor offers remote support/updates that could
touch data, this classification changes and the support model must be
separately defined. Legal confirmation required.)*

## 1. Vertraulichkeit (Confidentiality)

**Zutrittskontrolle / Zugangskontrolle (Access Control):**
- Rollenbasierte Zugriffskontrolle (RBAC) mit granularen Berechtigungen
  pro Rolle (`rag/crosscutting/security/` — Berechtigungsprüfung vor jedem
  Endpunktzugriff).
- Multi-Faktor-Authentifizierung (MFA) verfügbar (`rag/crosscutting/security/mfa.py`).
- Sitzungs-Widerruf: eine entzogene Berechtigung wirkt sich auf die
  nächste Anfrage des Nutzers aus (Session-Invalidierung).

**Zugriffskontrolle (Transport & Speicherung):**
- TLS-Terminierung durch einen vorgeschalteten nginx-Reverse-Proxy
  (`nginx/nginx.conf`), selbstsigniertes Zertifikat wird bei der Installation
  automatisch erzeugt (`rag/bootstrap/tls_cert.py`), HTTP→HTTPS-Redirect,
  Security-Header (`Content-Security-Policy`, `Strict-Transport-Security`).
- Datenbank-Ports (Postgres, Redis, Neo4j) sind nicht auf dem Host
  veröffentlicht — nur der Reverse-Proxy ist erreichbar
  (`docker-compose.yml`).
- Container laufen als Nicht-Root-Benutzer, mit einem schreibgeschützten
  Root-Dateisystem und ohne zusätzliche Linux-Capabilities (`Dockerfile`,
  `docker-compose.yml`).

**Verschlüsselung (Encryption):**
- Envelope-Encryption-Keystore für Geheimnisse und Schlüssel im Ruhezustand
  (`rag/crosscutting/security/keystore.py`).
- Pro-Konversation-Schlüssel für krypto-basierte Löschung (Crypto-Shred,
  siehe `Loeschkonzept.md`).

**Pseudonymisierung:**
Siehe Abschnitt "Geplant, nicht implementiert" unten — es existiert derzeit
**keine** automatische Pseudonymisierung von Freitext-Inhalten.

## 2. Integrität (Integrity)

**Manipulationssicheres Audit-Log:** jeder Audit-Eintrag verkettet einen
Hash über den vorherigen Eintrag (`rag/crosscutting/security/audit.py`,
`verify_chain()`) — eine nachträgliche Änderung oder Löschung eines
vergangenen Eintrags bricht die Kette und ist bei der nächsten Prüfung
erkennbar.

**Schema-Versionierung:** Datenbank- und Vektorspeicher-Migrationen sind
versioniert und werden pro Migration einzeln committet
(`rag/migrations/`), sodass ein fehlgeschlagener Migrationsschritt den
Datenbestand nicht in einem inkonsistenten Zwischenzustand belässt.

## 3. Verfügbarkeit und Belastbarkeit (Availability and Resilience)

**Backup/Restore:** verschlüsselte, Keystore-gesicherte Archive
(`rag/backup/`), tatsächlich getestetes Restore-Verfahren (nicht nur
angenommen).

**Ressourcenbegrenzung:** Pro-Nutzer-Rate-Limits auf Dokumenten-Upload und
Chat-Endpunkten (`rag/crosscutting/security/rate_limit.py`), mit
kontrolliertem Fail-Open-Verhalten bei einem Ausfall des Redis-Backends
statt eines harten Fehlers für alle Nutzer. Zusätzlich eine
Pro-Nutzer-Obergrenze für gleichzeitig wartende Ingestions-Aufträge
(`rag/crosscutting/security/ingestion_limits.py`).

## 4. Verfahren zur regelmäßigen Überprüfung (Regular Testing Procedures)

- **Kontinuierliche Sicherheitsprüfung in der CI-Pipeline:** Container-
  Image-Scanning auf bekannte Schwachstellen (Trivy) bei jedem Merge, mit
  hartem Ausschlussgrenzwert für Schwachstellen der Kategorie CRITICAL
  (`.github/workflows/ci.yml`).
- **Automatisierte Sicherheits-Testsuite:** Unit- und Integrationstests
  für Zugriffskontrolle, Verschlüsselung, Löschkonzept-Präzedenz und
  Audit-Manipulationserkennung laufen bei jedem Merge.
- **Retrieval-Qualitätsprüfung:** ein automatisierter Regressionstest
  gegen einen kuratierten Golddatensatz läuft bei jedem Merge in die
  Hauptentwicklungslinie (`eval/table_ab.py`).

## Geplant, nicht implementiert (Planned, Not Implemented)

Die folgenden Maßnahmen werden in der Quellspezifikation dieses Projekts
erwähnt, sind jedoch **zum jetzigen Zeitpunkt nicht umgesetzt**. Sie dürfen
nicht als bestehende Kontrollen gegenüber Kunden oder Prüfern dargestellt
werden:

- **Automatisierte Pseudonymisierung** von Freitext-Dokumenteninhalten
  (z. B. mittels Microsoft Presidio) — keine entsprechende Abhängigkeit
  oder Implementierung im Quellcode vorhanden.
- **KI-Transparenz-Kennzeichnung** (AI Act): eine Kennzeichnung, dass eine
  Antwort von einem KI-System generiert wurde, sowie eine entsprechende
  Protokollierung, existiert derzeit nicht — weder in der Benutzeroberfläche
  noch im Audit-Log.

*(Both pseudonymization and AI-generated-content disclosure are referenced
in this project's own source specification as if already built — they are
not. This section exists specifically so this document does not
overclaim to a real auditor.)*
