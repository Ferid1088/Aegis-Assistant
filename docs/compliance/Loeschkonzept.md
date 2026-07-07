# Löschkonzept

*(Deletion Concept, Art. 17 DSGVO — Recht auf Löschung / Right to Erasure)*

> **Entwurf — vor Verwendung durch einen Rechtsanwalt/Datenschutzbeauftragten
> zu prüfen.** Insbesondere die Einordnung als Auftragsverarbeiter/
> Verantwortlicher (siehe `TOM.md`) bedarf rechtlicher Bestätigung.
>
> (Draft — must be reviewed by a lawyer/data protection officer before
> real use. In particular, the controller/processor classification
> requires legal confirmation.)

## Rangfolge: Legal Hold, Löschanfrage, Aufbewahrung, Soft-Delete

Diese Anwendung implementiert eine feste Rangfolge, wenn mehrere
Richtlinien in Konflikt stehen (z. B. eine Aufbewahrungspflicht und eine
Löschanfrage nach Art. 17 gleichzeitig):

1. **Legal Hold (Rechtliche Aufbewahrungssperre)** hat immer Vorrang —
   auch vor einer Löschanfrage. Rechtsgrundlage: Art. 17 Abs. 3 lit. e)
   DSGVO (Geltendmachung, Ausübung oder Verteidigung von Rechtsansprüchen).
   Eine Löschanfrage gegen eine Konversation mit aktivem Legal Hold wird
   **abgelehnt und mit rechtlicher Begründung protokolliert**, nicht
   stillschweigend ignoriert.
2. **Löschanfrage (Erasure Request)** hat Vorrang vor der gewöhnlichen
   Aufbewahrungsfrist und vor einem "für immer" gesetzten Soft-Delete.
3. **Aufbewahrungsfrist (Retention Policy).**
4. **Soft-Delete** ist die Standard-Nutzeraktion: die Konversation
   verschwindet sofort aus der Oberfläche, verbleibt aber in der
   Datenbank. Dies ist **keine** DSGVO-Löschung im Sinne von Art. 17.

## Wie wird tatsächlich gelöscht: Crypto-Shred

Jede Konversation wird mit einem eigenen, pro-Konversation-Schlüssel
verschlüsselt. Eine Löschung im Sinne von Art. 17 erfolgt durch
**Vernichtung dieses Schlüssels**, nicht durch Löschen der Datenbankzeile
selbst — die verschlüsselten Daten (Chiffretext) werden dadurch
unwiederherstellbar, auch wenn eine Kopie in einem Backup verbleibt.
Implementiert im Keystore (`rag/crosscutting/security/keystore.py`) und in
der Löschanfrage-Verarbeitung.

**Warum dieser Ansatz:** eine physische Suche nach jeder Kopie eines
Datensatzes über alle Backups und Speicherorte hinweg ist unpraktikabel.
Crypto-Shredding erfüllt die Löschpflicht, ohne jedes Backup-Band
durchsuchen zu müssen — vorausgesetzt, der Schlüssel selbst wird
tatsächlich und nachweisbar vernichtet, nicht nur der Datenbankverweis
entfernt.

## Was wird gelöscht, wann

| Auslöser | Was passiert | Wo protokolliert |
|---|---|---|
| Nutzer löscht Konversation (Standardaktion) | Soft-Delete: aus der UI entfernt, Daten bleiben in der Datenbank | Audit-Log (Zustandsänderung) |
| Löschanfrage (Art. 17), kein Legal Hold | Crypto-Shred: Schlüssel vernichtet, Chiffretext unwiederherstellbar, Datensatz als gelöscht markiert | Audit-Log (Löschanfrage + Ausführung) |
| Löschanfrage (Art. 17), aktiver Legal Hold | Löschung **abgelehnt** | Audit-Log (Löschanfrage + Ablehnung mit Rechtsgrundlage) |
| Aufbewahrungsfrist abgelaufen | Reguläre Löschung gemäß Aufbewahrungsrichtlinie | Audit-Log |

## Ausnahme: Legal Hold

Ein Legal Hold kann von einem Administrator gesetzt werden, um eine
Konversation vor jeglicher Löschung zu schützen (z. B. bei einem
laufenden Rechtsstreit). Solange ein Legal Hold aktiv ist, überschreibt
er jede andere Löschregel — einschließlich einer expliziten
Löschanfrage nach Art. 17. Das Setzen und Aufheben eines Legal Hold wird
im manipulationssicheren Audit-Log protokolliert (siehe `TOM.md`,
Abschnitt Integrität).
