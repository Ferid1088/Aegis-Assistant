# Löschkonzept

*(Deletion Concept, Art. 17 DSGVO — Recht auf Löschung / Right to Erasure)*

> **Entwurf — vor Verwendung durch einen Rechtsanwalt/Datenschutzbeauftragten
> zu prüfen.** Insbesondere die Einordnung als Auftragsverarbeiter/
> Verantwortlicher (siehe `TOM.md`) bedarf rechtlicher Bestätigung.
>
> (Draft — must be reviewed by a lawyer/data protection officer before
> real use. In particular, the controller/processor classification
> requires legal confirmation.)

## Rangfolge (Precedence Order): Legal Hold, Löschanfrage, Aufbewahrung, Soft-Delete

Diese Anwendung implementiert eine feste Rangfolge, wenn mehrere
Richtlinien in Konflikt stehen (z. B. eine Aufbewahrungspflicht und eine
Löschanfrage nach Art. 17 gleichzeitig). Implementiert in
`rag/domain/conversation.py`s Zustandsautomat und `resolve_erasure()`:

1. **Legal Hold (Rechtliche Aufbewahrungssperre)** hat immer Vorrang —
   auch vor einer Löschanfrage. Rechtsgrundlage: Art. 17 Abs. 3 lit. e)
   DSGVO (Geltendmachung, Ausübung oder Verteidigung von Rechtsansprüchen).
   Eine Löschanfrage gegen eine Konversation mit aktivem Legal Hold wird
   **abgelehnt**, nicht stillschweigend ignoriert (die Ablehnung wird über
   die API als reguläre Antwort mit Begründung zurückgegeben).
2. **Löschanfrage (Erasure Request)** hat Vorrang vor der gewöhnlichen
   Aufbewahrungsfrist und vor einem "für immer" gesetzten Soft-Delete.
3. **Aufbewahrungsfrist (Retention Policy)** — ist als Zweig in
   `resolve_erasure()` codiert, ist aber **praktisch nicht erreichbar**:
   Der einzige Aufrufer von `resolve_erasure()` ist `request_erasure()`
   in `conversation_service.py`, und dieser setzt `erasure_requested =
   True` bereits *bevor* `resolve_erasure()` aufgerufen wird (Stufe 2
   ist damit über diesen Pfad immer erfüllt, sodass die
   Aufbewahrungsfrist-Prüfung nie erreicht wird). Hinzu kommt: es gibt
   derzeit **keine** API, über die `retention_days` für eine reale
   Konversation überhaupt gesetzt werden könnte (das Feld ist in
   `ConversationResponse` nur lesbar). Es existiert außerdem **kein**
   automatisierter Hintergrundjob, der eine abgelaufene
   Aufbewahrungsfrist von sich aus auslöst. Dieser Zweig wird heute nur
   durch Unit-Tests (`eval/test_05_2.py`), nicht durch den produktiven
   Codepfad, ausgeübt.
4. **Soft-Delete** ist die Standard-Nutzeraktion: der Zustand der
   Konversation wechselt auf `soft_deleted`, wodurch bestimmte Aktionen
   (Suchen, Ändern, Umbenennen, Anhängen) gesperrt werden. Die Daten
   bleiben vollständig in der Datenbank erhalten. Dies ist **keine**
   DSGVO-Löschung im Sinne von Art. 17. *(Hinweis: ob eine
   soft-gelöschte Konversation in einer Benutzeroberfläche sofort
   unsichtbar wird, hängt von einer Frontend-Implementierung ab, die
   nicht Teil dieses Repositories ist — hier wird nur das
   Backend-Verhalten beschrieben.)* Der zugehörige Zweig
   `keep_soft_deleted` in `resolve_erasure()` ist, aus demselben Grund
   wie die Aufbewahrungsfrist oben, über den produktiven Codepfad
   ebenfalls nicht erreichbar — der Soft-Delete-Zustand selbst
   (Zustandswechsel auf `soft_deleted`) ist jedoch real und unabhängig
   von `resolve_erasure()` über `transition_conversation()` implementiert.

## Wie tatsächlich gelöscht wird (How Deletion Actually Works Today)

**Realer Mechanismus:** eine Löschanfrage nach Art. 17 löst einen echten,
harten Datenbank-`DELETE` aller zugehörigen `ConversationTurn`-Zeilen aus
(`rag/domain/conversation_turn_service.py`, aufgerufen aus
`request_erasure()` in `rag/domain/conversation_service.py`). Für die
**aktive Datenbank** ist der Inhalt damit tatsächlich und unwiederbringlich
gelöscht.

**Vorhandener, aber noch nicht wirksamer Baustein — Crypto-Shred-Schlüssel:**
zusätzlich zum harten Löschen wird ein pro-Konversation-Schlüssel im
Keystore vernichtet (`rag/crosscutting/security/keystore.py`,
`delete_key()`). Dieser Schlüssel existiert bereits als Grundlage für ein
zukünftiges echtes Crypto-Shred-Verfahren — **er verschlüsselt jedoch
aktuell keinen Konversationsinhalt.** Die Spalten `question`,
`standalone_question`, `answer` und `citations` in der Datenbank sind
derzeit **Klartext**, nicht durch diesen Schlüssel (oder einen anderen)
verschlüsselt.

**Bekannte Lücke, die ein Rechtsanwalt/Datenschutzbeauftragter kennen
muss:** weil der Konversationsinhalt als Klartext gespeichert wird, macht
die Vernichtung des Schlüssels eine **Kopie in einem Backup, das vor der
Löschanfrage erstellt wurde, nicht automatisch unwiederherstellbar** — ein
solches Backup enthält den ursprünglichen Inhalt weiterhin im Klartext.
Der harte `DELETE` wirkt nur auf die aktive Datenbank, nicht rückwirkend
auf bereits existierende Backup-Archive. Eine vollständige Art.-17-Lösung,
die auch Backups einschließt, erfordert entweder (a) eine echte
Verschlüsselung der Konversationsinhalte mit dem bereits vorhandenen
Schlüssel, verbunden mit dessen Vernichtung bei Löschung, oder (b) eine
explizite Bereinigung/Rotation älterer Backup-Archive nach einer
Löschanfrage. Beides ist heute **nicht implementiert** und als
Weiterentwicklung vorzumerken.

## Was wird gelöscht, wann, und was wird tatsächlich protokolliert

| Auslöser | Was tatsächlich passiert | Wird protokolliert? |
|---|---|---|
| Nutzer löscht Konversation (Standardaktion) | Soft-Delete: Zustand wechselt zu `soft_deleted`, Daten bleiben vollständig in der Datenbank | *(nicht Teil der Löschanfrage-Prüfung selbst)* |
| Löschanfrage (Art. 17), kein Legal Hold | Harter `DELETE` der Konversationsinhalte + Vernichtung des (noch nicht wirksamen) Crypto-Shred-Schlüssels | **Nein — derzeit nicht im Audit-Log erfasst** |
| Löschanfrage (Art. 17), aktiver Legal Hold | Löschung **abgelehnt** | **Nein — derzeit nicht im Audit-Log erfasst** |
| Aufbewahrungsfrist abgelaufen | **Praktisch nicht erreichbar:** kein automatischer Hintergrundjob, keine API zum Setzen von `retention_days`, und der einzige Aufrufer von `resolve_erasure()` setzt vorher `erasure_requested = True` (siehe Rangfolge oben) | *(nicht erfasst — dieser Zweig wird im produktiven Codepfad nie erreicht)* |

**Bekannte Lücke:** anders als in einer früheren Entwurfsfassung dieses
Dokuments dargestellt, protokolliert das Audit-Log heute **ausschließlich
das Setzen/Aufheben eines Legal Hold** (siehe unten) — Löschanfragen,
deren Ausführung und deren Ablehnung werden derzeit **nicht** in das
manipulationssichere Audit-Log geschrieben. Dies widerspricht der
ursprünglichen Absicht des Audit-Moduls und sollte in einer zukünftigen
Erweiterung nachgezogen werden.

## Ausnahme: Legal Hold

Ein Legal Hold kann von einem Administrator gesetzt werden, um eine
Konversation vor jeglicher Löschung zu schützen (z. B. bei einem
laufenden Rechtsstreit). Solange ein Legal Hold aktiv ist, überschreibt
er jede andere Löschregel — einschließlich einer expliziten
Löschanfrage nach Art. 17. Das Setzen und Aufheben eines Legal Hold wird
tatsächlich im manipulationssicheren Audit-Log protokolliert (ein Ereignis
`conversation_legal_hold_set`, siehe `TOM.md`, Abschnitt Integrität) — dies
ist, im Gegensatz zu den Löschanfrage-Ereignissen oben, real implementiert
und verifiziert.
