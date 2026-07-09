# Verzeichnis von Verarbeitungstätigkeiten (Vorlage)

*(Records of Processing Activities Template, Art. 30 DSGVO)*

> **Entwurf — vor Verwendung durch einen Rechtsanwalt/Datenschutzbeauftragten
> zu prüfen.** Insbesondere die Einordnung als Auftragsverarbeiter/
> Verantwortlicher (siehe `TOM.md`) bedarf rechtlicher Bestätigung.
>
> (Draft — must be reviewed by a lawyer/data protection officer before
> real use. In particular, the controller/processor classification
> requires legal confirmation.)

## Hinweis zur Verwendung

Da diese Anwendung vollständig air-gapped und on-premises beim Kunden
betrieben wird, ist regelmäßig **der Kunde der datenschutzrechtlich
Verantwortliche** (siehe `TOM.md`). Die Pflicht zur Führung eines
Verzeichnisses von Verarbeitungstätigkeiten (Art. 30 DSGVO) trifft daher
grundsätzlich den Kunden, nicht den Hersteller dieser Software.

Diese Vorlage füllt die Spalten aus, die der Hersteller aus technischer
Sicht bereits kennt (welche Datenkategorien die Software verarbeitet,
welche technischen Maßnahmen greifen). Die kundenspezifischen Spalten
(eigene Organisation, eigener Zweck, eigener Verantwortlicher/DPO-Kontakt)
sind als Platzhalter markiert und **vom Kunden auszufüllen**.

## Verzeichniseintrag: [VOM KUNDEN AUSZUFÜLLEN — Name der Verarbeitungstätigkeit]

| Feld | Inhalt |
|---|---|
| **Verantwortlicher** | [VOM KUNDEN AUSZUFÜLLEN: Name, Anschrift, Kontakt des Verantwortlichen] |
| **Vertreter des Verantwortlichen** (falls zutreffend) | [VOM KUNDEN AUSZUFÜLLEN] |
| **Datenschutzbeauftragte(r)** | [VOM KUNDEN AUSZUFÜLLEN: Name und Kontaktdaten] |
| **Zweck der Verarbeitung** | [VOM KUNDEN AUSZUFÜLLEN — z. B. "Interne Wissensdatenbank-Abfrage per KI-gestütztem Retrieval"] |
| **Kategorien betroffener Personen** | [VOM KUNDEN AUSZUFÜLLEN — abhängig von den hochgeladenen Dokumenten, z. B. Mitarbeitende, Kunden] |
| **Kategorien personenbezogener Daten** | Abhängig vom Inhalt der durch den Kunden hochgeladenen Dokumente; die Software selbst verarbeitet zusätzlich: Nutzerkonten (Benutzername, Passwort-Hash), Sitzungsdaten, Konversationsverläufe (Fragen und generierte Antworten), Audit-Log-Einträge (wer hat wann welche Aktion durchgeführt) |
| **Empfänger / Kategorien von Empfängern** | Keine Übermittlung an Dritte durch die Software selbst (air-gapped, on-premises). [VOM KUNDEN AUSZUFÜLLEN, falls eigene Empfänger bestehen] |
| **Übermittlung in Drittländer** | Keine — die Anwendung läuft vollständig air-gapped auf der eigenen Infrastruktur des Kunden. |
| **Löschfristen** | Siehe `Loeschkonzept.md`. [VOM KUNDEN AUSZUFÜLLEN, falls eigene, striktere Fristen gelten] |
| **Technische und organisatorische Maßnahmen** | Siehe `TOM.md`. |
