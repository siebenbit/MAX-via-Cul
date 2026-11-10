# MAX! via CUL

[English](README.en.md) | [Deutsch](README.md)

Home-Assistant-Custom-Integration fuer eQ-3 MAX!-Komponenten an einem mit
CULFW geflashten CUL oder CUNO.

Die Integration spricht direkt mit dem CUL per TCP und bildet nicht nur die
Grundfunktionen eines MAX! Cubes nach, sondern auch echte On-Device-
Assoziationen zwischen MAX!-Geraeten. Dadurch koennen Fensterkontakte,
Wandthermostate und Heizkoerperthermostate auch ohne laufenden Home Assistant
weiter sinnvoll zusammenarbeiten.

## Highlights

- Pairing neuer MAX!-Geraete direkt aus Home Assistant
- Temperatursteuerung fuer Heizkoerper- und Wandthermostate
- Wochenprofile mit Entwurfs-/Speicher-Workflow statt Sofort-Schreiben
- echte Gruppen-IDs und Link-Partner auf Geraeteebene
- virtuelle MAX!-Fensterkontakte fuer externe Sensorquellen wie Zigbee, Matter oder IKEA
- Diagnose-Entitaeten fuer `last_seen`, `stale`, `last_ack`, Retries und Kommunikationsstatus
- JSON-Export und -Import der bekannten MAX!-Topologie

## Zielbild

Die Integration ist auf einen robusten Alltagseinsatz mit alter, aber
weiterhin sehr brauchbarer MAX!-Hardware ausgelegt. Der Schwerpunkt liegt auf
lokaler Kommunikation, nachvollziehbarer Diagnose und moeglichst viel Logik
direkt auf den Geraeten statt ausschliesslich in Home Assistant.

## Architektur

Die Integration verbindet sich per TCP mit dem CUL und nutzt den MAX!/MORITZ-Modus des CULFW.

Wichtige Eigenschaften:

- lokale Kommunikation ohne Cloud
- zentrale serielle Command-Queue fuer Schreiboperationen
- ACK-basierte Wiederholungen bei Konfigurations- und Steuerbefehlen
- Pending-Config-Zustellung fuer schlafende MAX!-Fensterkontakte nach FHEM-/Homegear-Muster
- Persistenz aller bekannten Geraete und ihrer wichtigsten Topologie-Daten
- echte On-Device-Assoziationen statt reiner HA-in-the-loop-Automation
- kein automatisches WakeUp-Polling im Normalbetrieb, um Batterieverbrauch und
  Funklast niedrig zu halten

## Unterstuetzte Geraete

Aktuell ausgelegt fuer:

- MAX! Heizkoerperthermostate
- MAX! Heizkoerperthermostat+
- MAX! Wandthermostate
- MAX! Fensterkontakte
- virtuelle MAX!-Fensterkontakte innerhalb dieser Integration

## Einrichtung

### Voraussetzungen

- ein mit CULFW geflashter CUL/CUNO
- aktivierter TCP-Zugriff auf den CUL, typischerweise Port `2323`
- Home Assistant mit installiertem Custom Component `cul_max`

### Konfiguration

Die Integration wird ueber den Config Flow eingerichtet.

Dabei werden im Wesentlichen abgefragt:

- Hostname oder IP-Adresse des CUL
- TCP-Port
- eigene MAX!-Adresse der Integration

Hinweis:
Wenn ein bestehendes MAX!-Setup ersetzt wird, kann es sinnvoll sein, die Funk-Identitaet des alten Cubes sauber zu uebernehmen oder die Komponenten neu zu koppeln.

## Reset und Anlernen

Die folgenden Schritte sind als praxiserprobte Kurzreferenz fuer typische
MAX!-Geraete gedacht.

Vor dem Anlernen in Home Assistant:

1. `cul_max.start_pairing` aufrufen
2. danach das jeweilige Geraet in den Anlernmodus bringen

Wenn alles korrekt laeuft, sollte das Pairing in der Regel schnell
abgeschlossen sein.

### Heizkoerperthermostat

Reset:

1. Batterie entfernen.
2. Alle drei Tasten gleichzeitig gedrueckt halten.
3. Batterie wieder einsetzen.
4. Warten, bis im Display `res` erscheint.

Anlernen:

1. In Home Assistant das Pairing starten.
2. Am Thermostat die Boost-Taste fuer etwa 3 Sekunden gedrueckt halten.
3. Im Display erscheint ein Countdown von `30` nach `0`.
4. Das Geraet sollte waehrenddessen schnell angelernt werden.

### Fensterkontakt

Reset:

1. Batterie entfernen.
2. Taste gedrueckt halten.
3. Batterie wieder einsetzen.
4. Die Taste weiter gedrueckt halten. Zunaechst leuchtet die LED dauerhaft.
5. Taste erst loslassen, wenn der Sensor zu blinken beginnt.

Anlernen:

1. In Home Assistant das Pairing starten.
2. Die Taste am Fensterkontakt fuer etwa 3 Sekunden gedrueckt halten.
3. Die LED beginnt zu blinken.
4. Das Geraet sollte dann angelernt werden.

### Wandthermostat

Reset:

1. Beide Batterien entfernen.
2. Wirklich einige Zeit warten.
3. `Mond`, `Boost/OK` und `Minus` gleichzeitig gedrueckt halten.
4. Batterien wieder einsetzen.
5. Zuerst erscheint kurz eine Versionsanzeige, danach `res` im Display.

Hinweise:

- Beim Wandthermostat braucht man fuer den Reset je nach Softwareversion und
  Geraet manchmal mehrere Versuche.
- Bei manchen Versionen kommt man auch ueber einen langen Druck auf
  `Mode/Menu` ins Menue und kann dort `res` direkt auswaehlen.

Anlernen:

1. In Home Assistant das Pairing starten.
2. Das Wandthermostat in den Anlernmodus bringen.
3. Nach dem Reset muss am Wandthermostat gelegentlich einmalig die Uhrzeit
   gesetzt werden.
4. In der Regel bekommt das Geraet Uhrzeit und weitere Basisdaten nach dem
   erfolgreichen Pairing aber auch automatisch vom Cube bzw. von der
   Integration.

## Entitaeten

Je nach Geraetetyp stellt die Integration mehrere Entitaeten bereit.

### Klima

Fuer Heizkoerper- und Wandthermostate:

- `climate`-Entitaet fuer Solltemperatur und HVAC-Modus
- `text`-Entitaet fuer Wochenprofile
- `number`-Entitaeten fuer Komfort-/Tagtemperatur, Eco-/Nachttemperatur,
  Fenster-offen-Temperatur und Fenster-offen-Dauer
- `button`-Entitaeten fuer `Save Configuration` und `Discard Draft`
- optionale Lovelace-Karte fuer eine kompakte Wochenplan-Ansicht

Hinweis zur Sollwert-Semantik:

- Eine Solltemperatur-Aenderung respektiert den aktuellen MAX!-Modus jetzt
  moeglichst weit. Wird die Temperatur im `auto`-Betrieb geaendert, bleibt das
  Geraet aus Sicht der Integration im automatischen Kontext, statt sofort hart
  auf `manual` zu wechseln.
- Fuer die Diagnose stehen an der `climate`-Entitaet zusaetzlich
  `mode_detail` und `mode_is_temporary` zur Verfuegung. Damit laesst sich
  besser erkennen, ob ein Thermostat gerade wirklich im normalen
  Wochenprogramm laeuft oder in einem temporaeren Geraetezustand steckt.

### Fensterkontakte

Fuer echte und virtuelle MAX!-Fensterkontakte:

- `binary_sensor` fuer offen/geschlossen

### Diagnose

Pro bekanntem Geraet zusaetzlich:

- `sensor` fuer `Last Seen`
- `sensor` fuer `Last Ack`
- `sensor` fuer `Last Command Success`
- `sensor` fuer `Last Time Sync`
- `sensor` fuer `Expected Week Profile Temperature`
- `sensor` fuer `Week Profile Validation`
- `sensor` fuer `Retry Count`
- `sensor` fuer zusammengefassten Kommunikationsstatus
- `binary_sensor` fuer `Stale`, wenn ein Geraet zu lange keinen Funkkontakt hatte
- `binary_sensor` fuer `Config Pending`, wenn ausstehende Geraetekonfigurationen noch nicht zugestellt wurden

Integrationsweit zusaetzlich:

- `binary_sensor` fuer `Pairing Mode`, wenn das Anlernfenster gerade offen ist

Auf der Integrations- und Geraeteseite werden kritische Zustaende ausserdem
bereits in der Modellbezeichnung zusammengefasst, z. B.:

- `MAX! ShutterContact · discovered`
- `MAX! HeatingThermostat · pending config`

Wichtige Diagnoseattribute an den Entitaeten:

- `group_id`
- `linked_partners`
- `peer_names`
- `peer_labels`
- `is_paired`
- `pairing_state`
- `pending_config`
- `config_pending`
- `last_command`
- `last_time_sync_at`
- `last_reported_time`
- `expected_week_profile_temperature`
- `week_profile_validation`
- `week_profile_validation_reason`
- `actual_target_temperature`
- `temperature_delta_to_expected`
- `window_open_active`
- `open_window_partners`
- `open_window_partner_names`
- `pending_queue_type`
- `pending_queue_length`
- `pending_queue_current`
- `pending_queue_attempts`
- `pending_queue_last_error`
- `pending_queue_next_attempt_at`
- `supported_partner_types`

Fuer ausstehende Konfigurationsschritte werden zusaetzlich Queue-Metadaten
angezeigt. Damit ist auf einen Blick erkennbar, ob eine Pending-Konfiguration
noch aktiv abgearbeitet wird, welcher Schritt gerade vorne in der Queue steht
und wann der naechste Retry versucht wird. Klima-Queues werden nach Homegear-
Vorbild im Hintergrund weiter aufgenommen, auch wenn der erste Versuch nicht
vollstaendig durchging.

`Week Profile Validation` ist eine Best-Effort-Diagnose und kein echtes
Readback vom Geraet. Die Entitaet bewertet den aktuellen Zustand aus
Wochenprofil, aktuellem Sollwert, Betriebsmodus, Fensterstatus und
`Config Pending`, zum Beispiel als:

- `likely_applied`: aktueller Sollwert passt zum erwarteten Wochenprofil
- `pending`: Profil oder andere Klimakonfiguration ist noch nicht vollstaendig zugestellt
- `window_open`: ein verknuepfter Fensterkontakt ist offen
- `manual_override` / `temporary_override` / `boost`: das Geraet laeuft gerade nicht rein nach Wochenprogramm
- `mismatch`: erwarteter Profilwert und tatsaechlicher Sollwert passen nicht zusammen
- `unknown`: es gibt noch nicht genug Informationen fuer eine belastbare Aussage

Zusaetzlich gibt es eine Diagnose-Entitaet `Pairing State`.

Bedeutung der Pairing-Zustaende:

- `paired`: Das Geraet wurde sauber ueber den Pairing-Prozess dieser
  Integration angelernt.
- `discovered`: Das Geraet wurde bereits per Funk gesehen, ist aus Sicht der
  Integration aber noch nicht wirklich neu gepairt. Das ist typisch bei
  Migrationen von einem alten MAX! Cube oder einem anderen Setup.
- `virtual`: Ein von der Integration angelegtes virtuelles Geraet.

## Services

Die Services koennen direkt aus Home Assistant aufgerufen werden. Die komplette Feldbeschreibung liegt in [services.yaml](./services.yaml).

Viele der operativen Services liefern in den Entwicklerwerkzeugen inzwischen
auch direkt eine Service-Response zurueck, zum Beispiel fuer Topologie-Import,
Raum-Assoziationen, Zeit-Sync oder Cleanup-Dry-Runs. Damit lassen sich
Ergebnisse oft direkt pruefen, ohne erst ins Log schauen zu muessen.

`cul_max.start_pairing` unterstuetzt optional `duration` in Sekunden. Damit kann das Anlernfenster fuer groessere Wohnungen oder schrittweises Anlernen bewusst laenger offen bleiben.

`cul_max.sync_time` sendet die aktuelle lokale Uhrzeit an einzelne oder alle
bekannten Thermostate und Wandthermostate. Das ist besonders dann sinnvoll,
wenn Wochenprogramme offensichtlich nicht zum aktuellen Wochentag oder zur
Uhrzeit passen.

`cul_max.set_desired_temperature` erlaubt bewusstes Setzen von Sollwerten im
Stil von FHEM/MAX!: `auto`, `manual`, `boost` oder temporaer bis zu einem
`until`-Zeitpunkt. Damit lassen sich Tests und Fehlersuche deutlich sauberer
durchfuehren als mit reinem `climate.set_temperature`, wenn ein Thermostat
gerade nicht klar zwischen Wochenprogramm und temporaerem Override zu
unterscheiden scheint.

### Pairing bequem vom Handy starten

Fuer den Alltag ist es oft angenehmer, das Pairing nicht jedes Mal manuell aus
den Entwicklerwerkzeugen zu starten, sondern ueber ein Script oder einen
Lovelace-Button.

Beispiel als Script:

```yaml
script:
  cul_max_pairing_60s:
    alias: MAX Pairing 60s
    sequence:
      - action: cul_max.start_pairing
        data:
          duration: 60
```

Direkt als Lovelace-Button:

```yaml
type: button
name: MAX Pairing
icon: mdi:link-variant-plus
tap_action:
  action: perform-action
  perform_action: cul_max.start_pairing
  data:
    duration: 60
```

### Uhrzeit der Thermostate pruefen und synchronisieren

MAX!-Wochenprogramme laufen auf den Geraeten selbst. Wenn ein Thermostat die
falsche Uhrzeit oder den falschen Wochentag kennt, wirkt das in Home Assistant
oft so, als sei das Wochenprofil fehlerhaft, obwohl in Wirklichkeit nur die
Geraeteuhr nicht stimmt.

Zur Kontrolle helfen vor allem diese Diagnosewerte:

- `Last Time Sync`
- `last_reported_time`

Zum manuellen Nachziehen der Uhrzeit:

```yaml
action: cul_max.sync_time
data:
  entity_id: climate.thermostat_kinderzimmer
```

Oder fuer alle gepairten MAX!-Thermostate und Wandthermostate gleichzeitig:

```yaml
action: cul_max.sync_time
data: {}
```

Hinweise:

- Nach dem Pairing versucht die Integration bereits, die Uhrzeit an
  Thermostate und Wandthermostate zu senden.
- Zusaetzlich verteilt die Integration die Climate-Geraete auf 12 stundenweise
  Time-Slots und sendet im Hintergrund einen sparsamen periodischen Zeitabgleich.
- Bei auffaelligem Wochenprogramm-Verhalten lohnt sich trotzdem ein
  expliziter Zeitabgleich.
- Gerade nach Migrationen von Cube, FHEM oder Homegear kann eine falsche
  Geraeteuhr leicht uebersehen werden.

Mit Script als Zwischenschritt:

```yaml
type: button
name: MAX Pairing
icon: mdi:link-variant-plus
tap_action:
  action: perform-action
  perform_action: script.cul_max_pairing_60s
```

Fuer groessere Wohnungen oder wenn man mit dem Telefon zum Geraet laufen muss,
sind `90` oder `120` Sekunden oft entspannter.

Passende Statusanzeige fuer das Dashboard:

```yaml
type: tile
entity: binary_sensor.max_via_cul_pairing_mode
name: MAX Pairing
```

Die Diagnose-Entitaet `Pairing Mode` zeigt, ob das Anlernfenster gerade offen
ist. In den Attributen stehen ausserdem `pairing_until` und
`remaining_seconds`.

Hinweise:

- Die genaue `entity_id` der Pairing-Status-Entitaet kann je nach bestehendem
  Bestand leicht abweichen. Im Zweifelsfall in Home Assistant nach `Pairing Mode`
  der Integration `cul_max` suchen.
- Ein laufendes Pairing-Fenster ist integrationsweit, nicht pro Geraet.
- Wer sehr oft testet, sollte die Dauer nicht unnoetig hoch ansetzen, um
  versehentliche Anlernvorgaenge zu vermeiden.

### Grundfunktionen

- `cul_max.start_pairing`
- `cul_max.set_device_name`
- `cul_max.wake_thermostats`
- `cul_max.set_temperature_config`
- `cul_max.set_week_profile`
- `cul_max.set_week_profile_days`

Hinweis zu `wake_thermostats`:
Der Dienst ist bewusst nur manuell gedacht. MAX!-WakeUp haelt den Empfaenger des
Geraets offen und erhoeht bei haeufiger Nutzung Batterieverbrauch und Funklast.
Die Integration fuehrt deshalb kein periodisches WakeUp-Polling im Hintergrund
mehr aus.

### On-Device-Assoziationen

- `cul_max.set_group_id`
- `cul_max.remove_group_id`
- `cul_max.add_link_partner`
- `cul_max.remove_link_partner`
- `cul_max.associate_devices`
- `cul_max.deassociate_devices`

### Virtuelle Fensterkontakte

- `cul_max.create_virtual_shutter_contact`
- `cul_max.delete_virtual_device`
- `cul_max.send_virtual_shutter_contact_state`

### Komfortdienste fuer ganze Raeume

- `cul_max.create_room_association`
- `cul_max.delete_room_association`
- `cul_max.rebuild_room_association`

### Backup und Restore

- `cul_max.export_topology`
- `cul_max.import_topology`
- `cul_max.cleanup_superseded_devices`

### Service-Empfehlung

Im Alltag reichen meist die Komfortdienste:

- `create_room_association`
- `delete_room_association`
- `rebuild_room_association`
- `send_virtual_shutter_contact_state`

Die Low-Level-Dienste bleiben bewusst erhalten, weil sie beim Reparieren,
Migrieren und Debuggen sehr hilfreich sind:

- `set_temperature_config`
- `set_group_id`
- `remove_group_id`
- `add_link_partner`
- `remove_link_partner`
- `associate_devices`
- `deassociate_devices`
- `cleanup_superseded_devices`

Der aktuelle Stand der Integration nutzt alle registrierten Services noch
sinnvoll; es gibt derzeit keine veralteten Leichen-Services.

## Beispiele

### Komfort-, Nacht- und Fenster-offen-Temperatur

MAX! kennt diese Werte auch aus FHEM und Homegear als echte
Geraetekonfiguration:

- `comfortTemperature` = Tag-/Komforttemperatur
- `ecoTemperature` = Nacht-/Absenktemperatur
- `windowOpenTemperature` = Zieltemperatur bei offenem Fenster
- `windowOpenDuration` = Dauer der Fenster-offen-Absenkung

In Home Assistant erscheinen sie als `number`-Entitaeten am Thermostat.
Alternativ kann alles gesammelt ueber den Service gesetzt werden:

```yaml
service: cul_max.set_temperature_config
data:
  entity_id: climate.thermostat_bad
  comfort_temperature: 21.0
  eco_temperature: 17.0
  window_open_temperature: 12.0
  window_open_duration: 15
```

Hinweis:
Die `text`- und `number`-Entitaeten senden Aenderungen nicht mehr sofort. Sie
landen zuerst als Entwurf im UI und werden erst ueber den Button
`Save Configuration` wirklich aufs Geraet geschrieben. Mit `Discard Draft`
laesst sich ein angefangener Entwurf wieder verwerfen.

Wichtiger Praxis-Hinweis zu Wochenprofilen:

- Das Schreiben von Wochenprofilen kann bei MAX! deutlich laenger dauern als
  einzelne Solltemperatur- oder Gruppenkommandos.
- Ursache sind die alte Funktechnik, das Protokoll selbst und die
  regulatorischen Funkgrenzen im 868-MHz-Band.
- Ein Wochenprofil besteht intern aus mehreren einzelnen Funkpaketen pro Tag
  und wird deshalb nicht immer "sofort" sichtbar vollstaendig uebertragen.
- Gerade auf Setups mit vielen Geraeten oder wenig Funkruhe kann es daher
  voellig normal sein, dass ein Profil schrittweise eingespielt wird und
  `Config Pending` zwischenzeitlich noch aktiv bleibt.
- Das ist kein grundsaetzliches Problem der Geraete: MAX! ist alte, aber
  alltagstaugliche Technik, und gerade deshalb auf dem Gebrauchtmarkt oft
  sehr attraktiv.

Wichtiger Praxis-Hinweis fuer Raeume mit Wandthermostat:

- Das Wochenprogramm sollte in solchen Raeumen in der Regel nur auf das
  Wandthermostat geschrieben werden.
- Die Verteilung auf die zugeordneten Heizkoerperthermostate uebernimmt MAX!
  intern innerhalb der Raumkopplung.
- Es ist normalerweise nicht noetig, dasselbe Wochenprogramm zusaetzlich noch
  einzeln auf alle Heizkoerperthermostate zu schreiben.

### Lovelace-Karte fuer Wochenprofile

Zusaetzlich zur Bearbeitung ueber die `text`-Entitaeten liegt eine kleine
Custom-Lovelace-Karte fuer Wochenprofile bei.

In Home Assistants normalem Lovelace-Storage-Modus wird die Karte
automatisch als Ressource registriert und erscheint danach auch im
visuellen Karteneditor. Sie kann dort direkt ueber die UI konfiguriert
werden.

Danach kann die Karte z. B. so verwendet oder ueber den Kartenpicker
angelegt werden:

```yaml
type: custom:cul-max-week-profile-card
entity: climate.thermostat_bad
title: Bad Wochenprofil
```

Hinweise:

- Bei bestehenden Setups mit alter manueller `/local/cul-max-week-profile-card.js`
  Ressource migriert die Integration den Eintrag im Storage-Modus
  automatisch auf den eingebetteten Pfad.
- Wer Lovelace im YAML-Modus betreibt, muss die Ressource weiterhin manuell
  eintragen, z. B. als `/cul-max/cul-max-week-profile-card.js` vom Typ
  `module`.
- Nach einem Update oder der ersten automatischen Registrierung kann ein
  Browser-Reload sinnvoll sein.
- Die Karte zeigt das Wochenprofil lesbar pro Tag und oeffnet beim Klick das
  Mehr-Infos-Dialogfenster der Climate-Entitaet

### Kompletten Raum aufbauen

```yaml
service: cul_max.create_room_association
data:
  room_name: Kueche
  climate_device_names:
    - Wandthermostat Kueche
    - Heizung Kueche Links
    - Heizung Kueche Rechts
  create_virtual_shutter_contact: true
  virtual_shutter_contact_name: Virtueller Fensterkontakt Kueche
  bidirectional: true
```

Wichtiger Praxis-Hinweis:

- Gerade bei Raeumen mit mehreren Fensterkontakten, Heizkoerperthermostaten
  oder Wandthermostaten kann die Kopplung zeitversetzt vollstaendig wirksam
  werden.
- Wenn ein Raum nach manuellen Vorarbeiten spaeter nochmals mit
  `create_room_association` aufgebaut wird, kann die Integration eine andere
  freie `group_id` waehlen als zuvor. Wer bereits manuell mit einer festen
  `group_id` gearbeitet hat, sollte diese beim Raumaufbau explizit mitgeben,
  um Mischzustaende zu vermeiden.
- Es kann notwendig sein, Fensterkontakte nach dem Aufbau des Raums ein paar
  Mal real zu betaetigen, also Fenster auf und wieder zu, damit ausstehende
  Konfigurationen wirklich bis in alle beteiligten Geraete hineinlaufen.
- Dabei sollte man nicht zu frueh von einem Fehler ausgehen oder die Geduld
  verlieren. `Config Pending` und die `Peers`-Diagnose helfen bei der
  Einordnung.
- Ein abschliessender Realtest ist immer sinnvoll: Fenster auf, Fenster zu,
  Solltemperatur aendern und pruefen, ob alle beteiligten Geraete wie erwartet
  reagieren.

### Externen Fensterkontakt auf virtuellen MAX!-Kontakt abbilden

Empfohlener Ablauf:

1. Virtuellen MAX!-Fensterkontakt anlegen oder einen bereits vorhandenen
   virtuellen Kontakt verwenden.
2. Den virtuellen Kontakt mit dem Zielraum verknuepfen, z. B. ueber
   `create_room_association`.
3. Den externen Sensor per Automation auf
   `cul_max.send_virtual_shutter_contact_state` abbilden.

Beispiel fuer einen bestehenden virtuellen Kontakt `A00000` im Raum `Buero`:

```yaml
action: cul_max.create_room_association
data:
  room_name: Büro
  climate_entity_ids:
    - climate.thermostat_buro
  window_addresses:
    - A00000
  bidirectional: true
```

Danach die eigentliche Abbildung des externen Sensors:

```yaml
alias: Externer Fensterkontakt Büro -> MAX virtuell
mode: single
trigger:
  - platform: state
    entity_id: binary_sensor.sensor_2_contact
condition:
  - condition: template
    value_template: "{{ trigger.to_state is not none and trigger.to_state.state in ['on', 'off'] }}"
action:
  - service: cul_max.send_virtual_shutter_contact_state
    data:
      address: A00000
      is_open: "{{ trigger.to_state.state == 'on' }}"
```

Was du danach pruefen solltest:

- `Pairing State` des virtuellen Kontakts ist `virtual`
- `Peers` am Thermostat zeigen den virtuellen Kontakt
- `Peers` am virtuellen Kontakt zeigen das Thermostat
- Beim Oeffnen/Schliessen des externen Sensors reagiert das MAX!-Thermostat autonom
- Virtuelle Fensterkontakte werden im Sendepfad bewusst bevorzugt behandelt,
  damit solche Automationen nicht hinter laenger laufenden Wochenprofil- oder
  Konfigurationsqueues blockieren.

Typische Stolpersteine:

- `create_virtual_shutter_contact: true` nur verwenden, wenn der virtuelle
  Kontakt wirklich neu angelegt werden soll. Existiert die Adresse schon, kommt
  ein Fehler.
- Ein bereits vorhandener virtueller Kontakt wird bei
  `create_room_association` ueber `window_addresses`, `window_entity_ids` oder
  `window_device_names` eingebunden, nicht ueber
  `virtual_shutter_contact_address` allein.
- `virtual_shutter_contact_address` hat nur eine Wirkung zusammen mit
  `create_virtual_shutter_contact: true`.
- Wenn ein echter MAX!-Thermostat im Zielraum nur `discovered` und noch nicht
  `paired` ist, blockiert die Integration das Schreiben absichtlich.
- Bei Problemen zuerst `Peers`, `Pairing State`, `Config Pending` und
  `Communication` der beteiligten Geraete pruefen.

### Topologie sichern

```yaml
service: cul_max.export_topology
data:
  path: backups/cul_max_topology.json
```

### Topologie wieder einspielen

```yaml
service: cul_max.import_topology
data:
  path: backups/cul_max_topology.json
  create_virtual_devices: true
  update_names: true
  apply_group_ids: true
  apply_links: true
  apply_week_profiles: true
```

### Migration und Altlasten aufraeumen

Bei Migrationen kann es vorkommen, dass Geraete zuerst nur als `discovered`
auftauchen oder alte Device-/Entity-Registry-Eintraege aus frueheren Adressen
stehen bleiben.

Empfohlenes Vorgehen:

1. Betroffene Geraete bei Bedarf resetten und wirklich neu ueber
   `cul_max.start_pairing` anlernen.
2. Danach `Pairing State` pruefen:
   `paired` bedeutet sauber uebernommen, `discovered` bedeutet nur gesehen.
3. Anschliessend Altlasten bereinigen.

Erst pruefen:

```yaml
service: cul_max.cleanup_superseded_devices
data:
  dry_run: true
```

Der `dry_run` liefert die gefundenen Kandidaten auch direkt als Service-Response
zurueck. Damit ist kein erhoehtes globales Log-Level noetig.

Falls auch alte, nur `discovered` uebernommene Altgeraete entfernt werden
sollen, kann der Cleanup diese zusaetzlich beruecksichtigen:

```yaml
service: cul_max.cleanup_superseded_devices
data:
  dry_run: false
  remove_registry_entries: true
  remove_discovered_devices: true
```

Dann wirklich entfernen:

```yaml
service: cul_max.cleanup_superseded_devices
data:
  dry_run: false
  remove_registry_entries: true
```

Der Cleanup entfernt:

- ersetzte (`superseded`) Altgeraete aus dem internen `cul_max`-Bestand
- auf Wunsch auch verwaiste Device- und Entity-Registry-Eintraege in Home Assistant

## Exportformat

Der JSON-Export enthaelt insbesondere:

- alle bekannten Geraete
- Geraeteadresse und Typ
- Anzeigenamen
- Gruppen-ID
- Link-Partner
- Wochenprofil als Hex und als lesbare Tageszeilen
- virtuelle Kontakte
- zuletzt bekannten Zustand des Geraets

Die erste Import-Version arbeitet bewusst defensiv:

- vorhandene Geraete werden aktualisiert
- fehlende virtuelle Fensterkontakte koennen angelegt werden
- Gruppen-IDs, Links und Wochenprofile koennen wiederhergestellt werden
- unbekannte physische Geraete werden nicht automatisch erzeugt
- bestehende zusaetzliche Links werden nicht aggressiv geloescht

## Hinweise zur Stabilitaet

Fuer einen stabilen Betrieb sind ein paar Punkte wichtig:

- Schlafende Thermostate vor Konfigurationsschritten wecken
- Fensterkontakte koennen Konfigurationsaenderungen zeitversetzt uebernehmen; `Config Pending` zeigt solche ausstehenden Schritte an
- Wochenprofile koennen wegen Paketanzahl und Funkgrenzen etwas laenger brauchen; auch hier ist `Config Pending` die wichtigste Orientierung
- Nach groesseren Raumkopplungen oder Umbauten sollte immer ein echter Abschlusstest folgen:
  Fensterkontakte real betaetigen, Solltemperaturen pruefen und die Reaktion aller beteiligten Geraete beobachten
- Nicht zwei Cubes mit derselben Funk-Identitaet parallel betreiben
- Bei vielen Schreiboperationen die serielle Abarbeitung der Integration nutzen
- `Last Seen`, `Stale` und Kommunikationssensoren fuer Ueberwachung verwenden

## Tests

Ein kleines Regressionstest-Paket fuer die wichtigsten Protokollpfade liegt
unter [tests/test_protocol.py](/home/tw/mnt/ha-config/custom_components/cul_max/tests/test_protocol.py).

Ausfuehren:

```bash
python3 custom_components/cul_max/tests/test_protocol.py -v
```

Abgedeckt sind aktuell unter anderem:

- FHEM-kompatible Kodierung der Wochenprofile
- Aufteilung von `ConfigWeekProfile` in die richtigen Teilpakete
- `SetTemperature`, `WakeUp` und `ShutterContactState` auf Byte-Ebene
- Parser-/Formatierungsregressionen rund um `24:00` und die letzte Tagestemperatur

## Bekannte Einschraenkungen

- Import stellt Topologie wieder her, ist aber noch kein vollstaendiger "Exact Restore"
- Hardwaretests haengen naturgemaess vom konkreten CULFW- und Geraeteverhalten ab

## Lizenz

Dieses Projekt soll, soweit mit den verwendeten Referenzen und der eigenen
Umsetzung kompatibel, unter der GNU General Public License, Version 3 oder
spaeter veroeffentlicht werden.

Die vollstaendige Lizenz liegt in [LICENSE](./LICENSE).

## Dank

Diese Integration waere ohne die Vorarbeit anderer Projekte in dieser Form kaum
entstanden. Viele Details des MAX!-Protokolls, zahlreiche praktische
Sonderfaelle und vor allem die robuste Behandlung alter eQ-3-Hardware liessen
sich erst sauber umsetzen, weil es mit FHEM und Homegear bereits zwei starke
Referenzen gibt.

Ein besonderer Dank geht daher an:

- das FHEM-Projekt und insbesondere die Module `10_MAX.pm` und
  `14_CUL_MAX.pm`, die bei Telegrammaufbau, Wochenprofilen, Zeitverhalten,
  Link-Logik und vielen Randfaellen eine enorme Hilfe waren
- Homegear, dessen Peer-, Queue- und Pending-Modell viele wertvolle Impulse
  fuer die robustere Umsetzung von Konfigurations- und Hintergrundablaeufen
  geliefert hat

In den ueberlassenen Referenzdateien sind unter anderem folgende
Autoren-/Copyright-Hinweise genannt:

- FHEM `10_MAX.pm` und `14_CUL_MAX.pm`:
  Matthias Gehre und Wzut, lizenziert unter der GNU General Public License,
  Version 2 oder spaeter
- Homegear `MAXCentral.cpp` und `MAXPeer.cpp`:
  `Copyright 2013-2019 Homegear GmbH`, lizenziert unter der GNU General Public
  License, Version 3 oder spaeter, zusaetzlich mit dokumentierter
  OpenSSL-Linking-Exception

Dieses Projekt ist eine eigenstaendige Home-Assistant-Integration, steht aber
ganz klar in einer Tradition freier Software, ohne die diese Umsetzung nicht
moeglich gewesen waere. Ziel ist es, die Integration, soweit kompatibel,
ebenfalls wieder unter einer aktuellen GPL zu veroeffentlichen und damit etwas
an diese offene Vorarbeit zurueckzugeben.

## GitHub und GUI-Link

Home Assistant zeigt fuer Custom Integrations in der Regel einen Weblink aus dem Feld `documentation` der [manifest.json](./manifest.json) an.

Sobald das Projekt in GitHub liegt, sollte dieses Feld auf die echte README oder eine kleine Docs-Seite zeigen, zum Beispiel:

```json
"documentation": "https://github.com/DEIN-NAME/cul_max/blob/main/README.md"
```

## Funkbudget

Der Controller wird beim TCP-Verbindungsaufbau und vor jeder Funkübertragung mit
`X` nach seinen tatsächlichen Credits gefragt. CULFW32 0.2.12 verwendet dasselbe
Format wie die geprüfte CULFW/a-culfw-Referenz: zwei Hexzeichen für `TX_REPORT`,
gefolgt von einem fünf Stellen breiten Dezimalfeld, beispielsweise `00  450`.
Es gibt nur einen TCP-Empfangsloop; Budgetantworten und MAX!-ACKs werden dort
getrennt zugeordnet. `X` ohne Argument verändert den Funkmodus nicht.

Die Firmwarekosten entsprechen `100 + (Paketbytes * 8) // 10` für `Zs`; bei `Zf`
entfällt der Präambelanteil. Das Längenbyte zählt mit. Zur Freigabe muss zusätzlich
ein Credit Reserve vorhanden sein. Das bisherige Wake-up-Verhalten und die
verwendeten Paketpräfixe bleiben erhalten. Maximal 900 Credits und 450 Credits
beim Firmwarestart sind Firmwarewerte, keine beim TCP-Reconnect angenommenen
Guthaben. Ein Credit entspricht 10 ms, die Regeneration einem Credit pro Sekunde.

Bei Budgetmangel bleibt das Paket ausstehend. Die nächste Abfrage erfolgt nach
fehlenden Credits plus einer Sekunde; lokale Regeneration erteilt niemals allein
eine Sendefreigabe. Im Leerlauf erfolgen keine periodischen Budgetabfragen. Eine
zusätzliche `X`-Abfrage nach jedem Funkpaket bildet eine Verarbeitungsbarriere:
Da `LOVF` keine Paketkennung enthält, wird erst danach das nächste Funkpaket
zugelassen. Diese TCP-Abfragen verbrauchen keine Funkcredits. Die Barriere
bestätigt die Firmwareverarbeitung, nicht den Empfang durch das MAX!-Gerät.

PairPong und virtuelle Fensterkontakte verwenden die bestehende Priorität.
Priorisierte Pakete werden vor noch nicht begonnenen normalen Funkpaketen
gewählt; innerhalb derselben Priorität gilt FIFO. Laufende Sendungen werden
nicht unterbrochen. Jede Priorität benötigt das volle Budget einschließlich
Reserve. Pairing kann bei erschöpftem Budget deshalb weiterhin einen erneuten
Versuch am Gerät erfordern. Empfangsabhängige Antworten warten außerhalb des
Empfangsloops. Geräte-ACKs behalten ihre eigene Zuordnung; ACK-Fristen starten
erst beim tatsächlichen Schreiben des Funkpakets.

Fehlende oder ungültige Budgetantworten geben keinen Versand frei. Nach drei
Sekunden wird eine Abfrage abgebrochen und die TCP-Verbindung erneuert, damit
verspätete Antworten nicht einer neuen Abfrage zugeordnet werden. Wartende
Pakete bleiben ausstehend. Abfragefehler und wiederholtes `LOVF` verwenden
Wartezeiten von 5, 10, 20, 40 bis maximal 60 Sekunden. Budgetwarten verbraucht
keine Geräte-ACK-Retries. Bei Verbindungsausfall nach einer Sendung bleibt deren
Zustellung ohne Geräte-ACK ungewiss; eine spätere Wiederholung ist möglich.

Am Controller-Gerät steht der Diagnose-Sensor **CUL Credits** bereit. Sein Zustand
ist der zuletzt gemeldete Wert; `budget_valid` zeigt dessen aktuelle Gültigkeit.
Weitere Attribute sind `next_packet_cost`, `required_credits`,
`waiting_for_budget`, `retry_in_seconds`, `next_attempt_at`,
`last_budget_query_at`, `last_budget_error` und `waiting_packets`. Ein alter Wert
bleibt nach Verbindungsverlust als Historie sichtbar, erlaubt aber keinen Versand.
Zeitangaben sind Schätzungen bis zur nächsten Prüfung, keine Sendegarantie.

Protokollgrundlage: [CULFW32 0.2.12 X-Abfrage](https://github.com/tostmann/culfw32/blob/1ce78f17a6a06b1aecf4bf53479b0f7165a25c8d/firmware/components/frontend_culfw/src/frontend_culfw.cpp#L1266-L1285),
[MAX!-Kosten](https://github.com/tostmann/culfw32/blob/1ce78f17a6a06b1aecf4bf53479b0f7165a25c8d/firmware/components/rf_proto_moritz/src/moritz_rf.cpp#L298-L307),
[FHEM credit10ms](https://github.com/mhop/fhem-mirror/blob/master/fhem/FHEM/00_CUL.pm)
und [FHEM MAX!-Warteschlange](https://github.com/mhop/fhem-mirror/blob/master/fhem/FHEM/14_CUL_MAX.pm).
Firmware mit inkompatibler Budgetantwort bleibt sicherheitshalber für den Versand
gesperrt.

## Sendewarteschlange verwalten

Ab Version 0.1.2 zeigt `custom:cul-max-queue-card` die allgemeine Sendewarteschlange
und die davon getrennten persistenten Konfigurationsaufträge. Die Karte wird im
Lovelace-Storage-Modus über die vorhandene Ressourcenregistrierung automatisch
hinzugefügt. Danach eine manuelle Karte mit folgender Konfiguration anlegen:

```yaml
type: custom:cul-max-queue-card
title: MAX! Warteschlange
```

Bei YAML-Ressourcenverwaltung zusätzlich diese Modulressource eintragen; bei
späteren Updates die Versionskennung anpassen:

```yaml
lovelace:
  resources:
    - url: /cul-max/cul-max-queue-card.js?v=0.1.4
      type: module
```

Der visuelle Editor bietet Titel, Controller, Geräteadresse, Status und Bereich.
Bei einem Controller erfolgt die Auswahl automatisch; bei mehreren muss ein
Controller gewählt werden. Optionale Kartenfelder: `config_entry_id`, `address`,
`status` und `scope` (`general` oder `configuration`). Die Karte lädt beim Öffnen,
bei Änderungen des Queue-Diagnosesensors und nach Wiederverbindung neue Daten.
Es gibt kein regelmäßiges Polling der Queue-Liste. Namen und Beschreibungen
werden als Text ausgegeben; Rohpakete sind nicht Bestandteil der Übersicht.

### Ersetzen und Löschen

Mehrere noch ungesendete SetTemperature-Anforderungen desselben Geräts ersetzen
sich: Nur der letzte vollständige Wunsch aus Temperatur, Auto-/Manuell-/Boost-
oder Urlaubsmodus und gegebenenfalls Endzeit bleibt stehen. Der neue Auftrag
steht am Ende der übrigen Befehle. Andere Geräte und Befehlstypen bleiben
unabhängig. Auch ein bereits auf Credits wartender Auftrag ist ersetzbar.
Wochenprofile, Gruppen-, Partner- und Pairing-Sequenzen werden nicht automatisch
zusammengefasst.

Die verbindliche Grenze ist der Aufruf von `writer.write()` unter dem
TCP-Schreiblock. Unmittelbar davor werden Abbruch und Ersetzung nochmals geprüft.
Ab Beginn der Übergabe bleibt der Auftrag bis zum Abschluss geschützt, auch
während ACK-Retries oder eines Reconnects. Ein Löschwunsch kann bereits gesendete
Pakete nicht zurücknehmen und bucht keine Credits zurück. Eine TCP-Trennung nach
Übergabe kann ohne Geräte-ACK keine eindeutige Zustellung garantieren; die
vorhandene Wiederholung kann das Paket erneut senden.

Die Karte unterstützt Einzel- und Mehrfachlöschung sowie bestätigtes Leeren.
Laufende Übertragungen und Protokollantworten sind geschützt. Interne Pakete
mehrteiliger Konfigurationen sind nicht einzeln löschbar. „Wartende Befehle leeren“
betrifft ausschließlich abbrechbare allgemeine Befehle des gewählten Controllers
und optionalen Gerätefilters, unabhängig vom angezeigten Statusfilter.

### Konfigurationsaufträge abbrechen

„Auftrag abbrechen“ benötigt eine gesonderte Bestätigung. Ein bereits gesendetes
Teilpaket beendet seinen ACK-/Retry-Ablauf; die übrigen Schritte werden entfernt.
Währenddessen lautet der Auftragsstatus `cancelling`, danach `cancelled`.
Abbruchabsicht und entfernte Schritte werden vor erfolgreicher Rückmeldung
persistiert, sodass sie nach Neustart nicht wieder aufgenommen werden.
Bereits bestätigte Teilpakete bleiben im Fortschritt dokumentiert. Bei bestehenden
Fensterkontakt-Abläufen ohne ACK wird eine angenommene Übertragung getrennt von
einer bestätigten Übertragung gezählt. Ein teilweise übertragenes Wochenprofil
wird nicht zurückgerollt; bei Bedarf ein vollständiges Profil erneut übertragen.

### Aktionen und Ergebnisse

Die Entwicklerwerkzeuge bieten folgende Aktionen. `get_queue` liefert
Response-Daten; die Änderungsaktionen können optional Response-Daten liefern.

```yaml
action: cul_max.get_queue
data:
  # Optional: config_entry_id, address, statuses, command_types, scope
  scope: general
response_variable: warteschlange
```

```yaml
action: cul_max.delete_queue_entry
data:
  entry_id: "UUID-aus-get_queue"
  # Alternativ: entry_ids: ["UUID-1", "UUID-2"]
```

```yaml
action: cul_max.clear_queue
data:
  # Bei mehreren Controllern erforderlich:
  # config_entry_id: "..."
  # Optional:
  address: "06473F"
```

```yaml
action: cul_max.cancel_config_job
data:
  job_id: "Auftrags-UUID-aus-get_queue"
  confirm: true
```

Snapshots enthalten Controller, allgemeine Einträge, Konfigurationsaufträge und
eine begrenzte Historie. Einzelnes Löschen eines inzwischen gesendeten Eintrags
liefert einen verständlichen Fehler. Sammellöschungen liefern `removed` und
`protected`. Temperatur- und virtuelle Fensterkontakt-Aktionen melden ihren
Abschlussstatus als `status`. `superseded` und `cancelled` sind erwartete Abbrüche,
keine Gerätebestätigung und kein Kommunikationsfehler. Ein ersetzter Climate-Aufruf
schreibt seinen alten Sollwert nicht nachträglich in die Oberfläche zurück.

Statuswerte: `queued`, `waiting_for_credits`, `sending`, `awaiting_ack`, `retrying`,
`completed`, `failed`, `cancelled`, `superseded`; Konfigurationsaufträge ergänzen
`cancelling`. Geräte-ACKs bleiben nach Nachrichtenzähler und Absender zugeordnet.
Zähler ersetzbarer Befehle werden erst beim ersten Versand vergeben und für
Retries beibehalten. Das acht Bit breite MAX!-Zählerformat wird nicht verändert.

Der Controller-Sensor **Sendewarteschlange** zeigt wartende Befehle. Attribute
enthalten aktive Befehle, Konfigurationsaufträge, aktuellen Befehl, Ersetzungs- und
Abbruchzähler, letzten Queue-Fehler und eine Änderungsrevision. Aktualisierungen
werden über 100 ms gebündelt. Allgemeine Befehle und ihre maximal 50 historischen
Einträge sind nicht neustartpersistent. Je Controller sind maximal 256 aktive oder
wartende allgemeine/interne Funkaufträge zugelassen; neue Anforderungen bei voller
Queue erhalten einen Fehler, vorhandene Aufträge werden nicht still verworfen.
Persistente Auftragsmetadaten verwenden Speicherschema 3, mit Migration vorhandener
Aufträge; maximal 50 abgeschlossene Auftragsdatensätze bleiben erhalten.

### Tests ohne Funkhardware

```sh
python3 -m unittest discover -s custom_components/cul_max/tests
node custom_components/cul_max/tests/frontend/queue-card.test.mjs
node --check custom_components/cul_max/frontend/cul-max-queue-card.js
git diff --check
```

Optionaler Browsercheck mit separat installiertem Playwright und Chromium:

```sh
python3 custom_components/cul_max/tests/frontend/check_queue_card.py
```

Dieser verwendet ausschließlich die lokale Testseite mit simulierten
Home-Assistant-Antworten. Playwright ist keine Laufzeitabhängigkeit der Integration.
Eine echte Home-Assistant-Laufzeit und Hardwarekommunikation müssen getrennt
von diesen Simulationstests geprüft werden.

### Zwei Sekunden Debouncing und sofortige Sollwertanzeige

Ab Version 0.1.3 werden SetTemperature-Benutzerwünsche je Thermostat erst nach
**2,0 Sekunden ohne weitere Änderung** an die Sendewarteschlange übergeben.
Jede neue Anforderung startet die Frist dieses Geräts neu. Temperatur, Auto-,
Manuell-, Boost- und Urlaubsmodus sowie die Endzeit bilden einen vollständigen
Wunsch. Andere Thermostate und zeitkritische Protokollbefehle werden dadurch
nicht verzögert. Der Eventloop kann die Ausführung nach der Frist verzögern,
aber ein Wunsch wird nicht vor Ablauf seiner zwei Sekunden eingereiht.

Die Climate-Entität zeigt den angenommenen Sollwert **sofort** an. Mehrere schnelle
Plus-/Minus-Klicks bauen auf diesem gewünschten Wert auf. Die zuletzt gemeldete
Gerätetemperatur bleibt getrennt gespeichert. Während des Debouncings und der
anschließenden Übertragung setzen ältere Zustandsmeldungen oder abgeschlossene
Vorgänger den neuen Wunsch nicht zurück. ACK und Gerätezustand werden getrennt
abgeglichen; siehe [Konsistente Thermostatzustände](#konsistente-thermostatzustände).
Auto ohne expliziten Sollwert wird nicht als 0 °C angezeigt. Vor dem Versand
abgebrochene Wünsche setzen Temperatur und Modus auf die neuesten gemeldeten
Werte zurück. Ein ACK-Timeout nach möglichem Versand gilt als unbestätigt.

Zusätzliche Climate-Attribute:

- `requested_target_temperature`: aktuell angezeigter gewünschter Sollwert, sonst `null`
- `reported_target_temperature`: zuletzt vom Gerät gemeldeter Sollwert
- `temperature_command_status`: Debounce-, Queue- oder Abschlussstatus

Die Queue-Karte zeigt die Vormerkung als **Wird gesammelt** (`debouncing`) mit
lokalem Countdown. Sie ist noch kein ausführbarer Funkauftrag und verbraucht
weder Credits noch Nachrichtenzähler oder Budgetabfragen. Ihre ID bleibt bei der
Übernahme in die Queue erhalten. Einzel- und Sammellöschung sowie „Queue leeren“
entfernen die Vormerkung einschließlich Timer. Eine gelöschte Vormerkung erscheint
nach Fristablauf nicht erneut. Die bestehende Latest-Value-Wins-Logik schützt auch
nach dem Einreihen weiterhin vor veralteten ungesendeten Werten; bereits gesendete
Befehle behalten ihre ACK-/Retry-Verarbeitung.

Eine bestehende Konfigurationswartezeit bleibt als Ausführungsbedingung erhalten:
Der Temperaturauftrag wird nach zwei Sekunden eingereiht, wartet gegebenenfalls
bis zum Ende der bereits laufenden Konfigurationsaufgabe oder maximal bis zehn
Sekunden nach Annahme. Der Worker kann währenddessen die Konfigurationspakete
weiter abarbeiten. Es gibt keinen zweiten blockierenden Konfigurations-Worker.

Beim Neuladen oder Herunterfahren werden ausstehende Timer beendet und ihre
Aufrufer mit `cancelled` abgeschlossen. Vormerkungen sind nicht persistent und
werden nach Neustart nicht automatisch gesendet. Sie gelten niemals allein durch
Ablauf des Timers als erfolgreich übertragen. Beim Abbruch eines HA-Aufrufers
bleibt ein bereits angenommener Wunsch dagegen bestehen, bis er ersetzt, manuell
gelöscht oder durch die Integration abgeschlossen wird.

Für manuell verwaltete Lovelace-Ressourcen lautet die aktuelle Cache-Kennung
`/cul-max/cul-max-queue-card.js?v=0.1.4`.

## Funkverkehr reduzieren (Version 0.1.4)

Die Optimierung behält Queue, Zwei-Sekunden-Debouncing, reale Credit-Abfragen,
Präambeln und ACK-/Retry-Grenzen bei. Die Einsparungen entstehen vor allem durch
weniger Zeitpakete und das Vermeiden bestätigter Wiederholungen.

| Änderung, nach erwartetem Nutzen | Einsparung | Bewertung |
| --- | --- | --- |
| Ein statt drei Zeitpakete | 224 Credits je Abgleich | Kleine Änderung; Zustellrate ohne Geräte-ACK nicht nachgewiesen gleich |
| Ausstehende Zeitabgleiche je Gerät zusammenfassen | Ein kompletter zusätzlicher Abgleich je Duplikat | Keine Änderung am Funkprotokoll |
| Auto-Folgeabgleich nur bei unbekannter, alter oder falscher Uhr | 112 weitere Credits, wenn der Abgleich entfällt | Gleiche Sechs-Stunden-Altersprüfung wie nach Konfiguration |
| ACK direkt vor erneutem Schreiben prüfen | 109–120 Credits je verhinderter Wiederholung | Gezielte Korrektur eines simuliert reproduzierten Rennens |
| Kurze Präambel automatisch verwenden | Theoretisch 100 Credits je Paket | Nicht umgesetzt: zuverlässiges Empfangsfenster nicht abgesichert |

### Paketkosten und Auslöser

Firmwarekosten mit langer Präambel, ohne Retries oder zusätzliche Zeitabgleiche:

| Vorgang | Pakete | Credits |
| --- | --- | --- |
| Solltemperatur, Auto oder Boost | 1 | 109 |
| Urlaub mit Endzeit | 1 | 112 |
| Zeitabgleich | 1, bisher 3 | 112, bisher 336 |
| Wochenprofil je Tag | 2 | 120 + 119 = 239 |
| Wochenprofil für sieben Tage | 14 | 1.673 |
| Temperaturkonfiguration | 1 | 114 |
| Gruppe setzen / entfernen | 1 | 109 / 108 |
| LinkPartner hinzufügen / entfernen | 1 | 112 |
| WakeUp oder PairPong | 1 | 109 |

Ein Zeitabgleich für zehn Thermostate benötigt damit 1.120 statt 3.360 Credits.
Ein Auto-Wechsel mit frischer Uhr benötigt 109 statt 445 Credits; bei notwendigem
Zeitabgleich 221 statt 445 Credits. Ein vollständiges Wochenprofil mit notwendigem
anschließendem Zeitabgleich benötigt 1.785 statt 2.009 Credits. Die Einsparungen
setzen eine Übertragung ohne Retries voraus. PairPong wird für jedes tatsächlich
bearbeitete PairPing gesendet; bei Climate-Geräten folgt weiterhin ein Zeitabgleich.

### Zeitabgleich

TimeInformation wird einmal gesendet. Gleichzeitige Anforderungen teilen einen
noch ungesendeten Auftrag desselben Geräts. Eine Geräteanfrage schützt einen
geteilten Auftrag vor manuellem Löschen. Wenn bereits geschrieben wurde, erhält
eine neue explizite Geräteanfrage einen neuen Auftrag; eine frühere Sendung gilt
nicht nachträglich als deren Antwort. Automatische Auslöser dürfen einen bereits
laufenden Auftrag teilen. Unterschiedliche Geräte bleiben unabhängig.

Automatische Zeitabgleiche innerhalb von 60 Sekunden nach einem erfolgreich
abgeschlossenen Abgleich derselben Integrationslaufzeit entfallen. Das vermeidet
beispielsweise einen unmittelbar auf den periodischen Abgleich folgenden
Startup-Abgleich. Ein gespeicherter Zeitstempel aus einem früheren HA-Lauf
unterdrückt den Startup-Abgleich nicht. Manuelle Abgleiche, Geräteanfragen und
bekannte Uhrabweichungen über fünf Sekunden umgehen die kurze Sperre.

Der verzögerte Auto-Folgeabgleich und der Konfigurationsabschluss senden nur bei
unbekannter Uhr, einem mindestens sechs Stunden alten Abgleich oder einer zuletzt
gemeldeten Abweichung über fünf Sekunden. Stündliche Slot-Prüfung, Zwölf-Stunden-
Geräteslots und bestehende periodische Mindestabstände bleiben erhalten. Der
Zeitstempel im Paket wird weiter erst unmittelbar beim Versand aktualisiert.

### Bewusst nicht geändert

Alle bisherigen `Zs`-Pakete bleiben `Zs`. CULFW32 unterstützt zwar `Zf`, aber eine
kurze Präambel setzt einen bereits empfangsbereiten Empfänger voraus. Eine gerade
empfangene Nachricht, ein ACK oder die Reihenfolge von Konfigurationspaketen
beweist kein ausreichend langes Empfangsfenster, besonders bei Credit-Wartezeiten.
Die geprüfte FHEM-Referenz enthält eine Fensterentscheidung, überschreibt sie
jedoch mit `needPreamble = 1`; ein zusätzlicher WakeUp vor Wochenprofilen ist dort
wegen beobachteter Paketverluste deaktiviert. Die Integration fügt ebenfalls keine
zusätzlichen automatischen WakeUps ein. Manuelle WakeUps und notwendige Gruppen-,
Partner- und Konfigurationsschritte werden nicht anhand alter Gerätezustände entfernt.

ACK-Fristen und Retry-Grenzen bleiben unverändert. Nachrichtenzähler, Absender
und jetzt auch die Zieladresse des ACK müssen zum gesendeten Paket passen. Ein
während Credit-Abfrage oder Schreiblock-Wartezeit eintreffendes gültiges ACK
verhindert die erneute Übergabe. Die ACK-Frist startet weiterhin erst beim Schreiben.

### Verbrauchsdiagnose

Der vorhandene Sensor **CUL Credits** enthält zusätzlich `traffic_started_at` und
`traffic_by_command`. Je Befehlstyp stehen zur Verfügung:

- `packets`: an den CUL übergebene Funk-Sendeversuche, auch abgelehnte
- `estimated_credits`: geschätzte Kosten dieser Versuche, ohne Freigabereserve
- `retries`: weitere Schreibversuche desselben Queue-Auftrags
- `firmware_rejections`: nach abgeschlossener Verarbeitungsbarriere zugeordnete `LOVF`-Ablehnungen
- `budget_delayed`: wegen unzureichender Credits verzögerte Aufträge, einmal je Auftrag

Die Werte beginnen bei Erstellung des Coordinators neu und werden nicht
persistiert. `X`, `Zr` sowie verworfene oder ersetzte ungesendete Wünsche sind kein
Funkverbrauch. Eindeutig zugeordnetes `LOVF` korrigiert die Kostenschätzung; bei
Verbindungsabbruch mit unklarem Ergebnis bleibt sie konservativ. Firmwareinterne
Sendungen und andere Clients sind nicht vollständig erfasst. Die Schätzung ist
kein Geräteempfangsnachweis und ersetzt niemals die echte Budgetabfrage über `X`.

Protokollgrundlage: [CULFW32 0.2.12 Kosten](https://github.com/tostmann/culfw32/blob/1ce78f17a6a06b1aecf4bf53479b0f7165a25c8d/firmware/components/rf_proto_moritz/src/moritz_rf.cpp#L298-L307),
[FHEM TimeInformation und Sendepfad](https://github.com/mhop/fhem-mirror/blob/master/fhem/FHEM/14_CUL_MAX.pm),
[FHEM Wochenprofil/WakeUp](https://github.com/mhop/fhem-mirror/blob/master/fhem/FHEM/10_MAX.pm).
FHEM erzeugt je Zeitabgleich eine Anforderung; seine generische Retry-Behandlung
ist davon getrennt. Eine unveränderte reale Zustellrate des einzelnen Zeitpakets
wurde ohne Hardwaretests nicht nachgewiesen. Die Änderungen sind mit simulierten
CUL-Antworten geprüft; sie erfordern keine Firmwareänderung oder neue Abhängigkeit.

## Konsistente Thermostatzustände

Der Coordinator berechnet Temperatur, Betriebsmodus und Preset gemeinsam aus dem
zuletzt gemeldeten Gerätezustand und dem aktuellen Benutzerwunsch. Gerätemeldungen
aktualisieren den gespeicherten tatsächlichen Zustand jederzeit, auch während
Debouncing und Budgetwartezeit. Beim Löschen eines ungesendeten Befehls fällt die
Anzeige sofort auf die **inzwischen neuesten** gemeldeten oder per ACK bestätigten
Werte zurück. Dafür
wird kein Rücksetzkommando gesendet. Ersetzte Vorgänger können einen neueren
Wunsch nicht überschreiben.

Ein ACK bestätigt die Annahme eines Kommandos, keine vollständige Statusmeldung.
Akzeptierte Temperatur und Betriebsart bleiben deshalb getrennt im Arbeitsspeicher
(`state_source: acknowledged`); die tatsächlich gemeldeten Werte werden dadurch
nicht verändert. **Es gibt keinen Abgleichtimer.** Ein alter gespeicherter Bericht
darf eine bestätigte Einstellung nicht allein durch Zeitablauf ersetzen. Auch bei
leerer Queue und ohne weitere Funkmeldung bleibt die bestätigte Einstellung sichtbar.

Nach ACK haben neue Gerätemeldungen für die tatsächlich enthaltenen Felder sofort
Vorrang. Das gilt auch für lokale Bedienung und Wochenprogrammwechsel. Ein
unvollständiges Wand-Kontrollpaket kann die Temperatur ändern, ohne den zuletzt
bestätigten Modus zu überschreiben. Wird ein neuerer, noch ungesendeter Wunsch
gelöscht, bleibt eine vorher bestätigte Einstellung erhalten. Ein passender
Gerätebericht ergibt `synchronized`; ein ACK allein bleibt `acknowledged`.

Ohne positives ACK gilt möglicher Versand als `unconfirmed`. Der optimistische
Anzeigewert bleibt ausdrücklich unbestätigt, bis ein tatsächlicher Bericht eintrifft;
eine neue Temperatur-/Modusmeldung hat sofort Vorrang. Eindeutiges Scheitern vor
Versand oder ein negatives ACK bedeutet `failed` und stellt die zuletzt gemeldeten
oder bestätigten Werte wieder her. Firmwarefehler `ZERR1/2` liegen vor der
Paketübergabe; `ZERR3` bleibt ungewiss. Ein abgewiesener Retry macht einen früheren
unbestätigten Versuch nicht ungeschehen. Ein negatives ACK gilt niemals als Erfolg.

MAX! liefert keinen verlässlichen Gerätezeitstempel für unaufgeforderte Berichte.
Die Empfangsreihenfolge ist daher bewusst maßgeblich: Ein wirklich verspätetes,
widersprüchliches Paket kann weiterhin einen neueren Wert ersetzen. Gerätemeldungen
lösen keine erneute Übertragung eines alten Wunsches aus.

| MAX!-Betriebsart | HA-Modus | Preset | Deutsche Anzeige |
| --- | --- | --- | --- |
| Automatik | `auto` | `none` | Automatik |
| Manuell | `heat` | `none` | **Manuell** |
| Boost | `heat` | `boost` | Manuell, Preset Boost |
| Urlaub / temporär bis | `heat` | `away` | Manuell, Preset Urlaub |
| Manuell 4,5 °C | `off` | `none` | Aus (Frostschutz) |

Frostschutz ist kein vollständiges Abschalten. Automatik bei 4,5 °C bleibt
Automatik. Temperaturänderungen übernehmen den wirksamen Modus einschließlich
einer vorhandenen Urlaubs-Endzeit. Preset `none` beendet Sonderbetrieb und wählt
Automatik. Neuen Urlaub über `cul_max.set_desired_temperature` mit `temperature`
und `until` starten; die Preset-Auswahl erfindet keine Endzeit. Urlaub wird dort
angeboten, wenn eine Endzeit bekannt oder Urlaub bereits aktiv ist.

`hvac_action` bleibt unbekannt: Aus einem geöffneten Ventil lässt sich keine
tatsächliche Wärmezufuhr beweisen. Die Standardkarte zeigt daher den Betriebsmodus
an. Heizkörperthermostate erhalten zusätzlich den Prozent-Sensor **Ventilstellung**.
Dieser und das Climate-Attribut `valve_position` enthalten den letzten wirklich
gemeldeten Wert; sein Alter ist über `last_reported_at` beziehungsweise
`valve_position_reported_at` sichtbar. Für Wandthermostate wird kein Ventilwert
erfunden. Auch unbekannter Modus oder Sollwert erhalten keine erfundenen Vorgaben.

Zusätzliche Climate-Attribute:

- `requested_target_temperature`, `requested_mode`: aktueller Anzeigewunsch, sonst `null`.
- `reported_target_temperature`, `reported_mode`: neueste tatsächliche Gerätemeldung.
- `command_status`: Queue-Status, `acknowledged`, `synchronized`, `unconfirmed` oder Abbruch-/Fehlerstatus.
- `temperature_command_status`: kompatibler Alias für `command_status`.
- `state_source`: `requested`, `acknowledged` oder `reported`.

Unvollständige Wandthermostatmeldungen überschreiben keine fehlenden Felder wie
Modus, Batterie, Ventilstellung oder Endzeit. Ein gemeldeter Moduswechsel kann
veraltete Sonderwerte ausdrücklich löschen. Beim Neustart werden ausschließlich
Gerätemeldungen wiederhergestellt; Benutzerwünsche und aus ACKs abgeleitete Werte
werden nicht als Geräteberichte gespeichert. Entladen beendet die Debounce-Tasks. Alte, künstlich erzeugte Wand-Ventilwerte
und Wand-Modi ohne nachweisbare Statusherkunft werden verworfen; der nächste volle
Wandbericht liefert den Modus wieder. Entitäts-IDs bleiben erhalten. Aktuelle
HA-Versionen verwenden die native Temperatur-API; ältere unterstützte Versionen
behalten einen Kompatibilitätszweig.

## Raumkonfiguration mit grafischem Wochenplan

Die neue Karte bearbeitet gemeinsam alle MAX!-Thermostate eines HA-Bereichs:
Komforttemperatur, Ecotemperatur, Fenster-offen-Temperatur, Fenster-offen-Dauer
und die sieben Tagesprofile. Das Raum-Dropdown verwendet HA-Bereiche. Eine
Bereichszuordnung der Climate-Entität hat Vorrang vor der Gerätezuordnung.
MAX!-Funkgruppen und Geräteverknüpfungen werden dadurch nicht geändert.

### Als eigene Dashboard-Ansicht hinzufügen

1. Weise deine MAX!-Thermostate in HA den gewünschten Bereichen zu.
2. Starte HA nach der Aktualisierung der Integration neu. Die JS-Ressource wird
   wie bei den bisherigen Karten automatisch registriert.
3. Erstelle in deinem Dashboard eine Ansicht im Layout **Panel (eine Karte)**.
4. Füge die Karte **MAX! Raumkonfiguration** über die Kartenauswahl hinzu, oder
   verwende diese YAML-Konfiguration:

```yaml
type: custom:cul-max-room-config-card
title: MAX! Raumkonfiguration
# Optional: Bereich beim Öffnen vorauswählen
# area_id: wohnzimmer
```

Der visuelle Karteneditor bietet Titel und Start-Raum an. Für YAML-Dashboards:

```yaml
resources:
  - url: /cul-max/cul-max-room-config-card.js
    type: module
```

Die Karte ist für Administratoren vorgesehen. Sie verwendet HA-Aktionen und ein
Admin-WebSocket-Abonnement, keine internen Python-Objekte und keine externen
JavaScript-Bibliotheken. Updates verwenden die vorhandene versionierte
Ressourcenregistrierung. Die bisherigen Wochenprofil- und Queue-Karten bleiben
verfügbar. Die Integration verändert keine bestehenden Dashboard-Ansichten.

### Entwurf und gemeinsames Speichern

Eingaben ändern zunächst nur den Entwurf. **Speichern** übernimmt alle geänderten
Werte gemeinsam für sämtliche Thermostate des gewählten Raums. Nicht geänderte
Blöcke und bereits bestätigte identische Werte erzeugen keine neuen Funkaufträge.
Bei unterschiedlichen Ausgangswerten erscheint **Gemischt**; es wird kein Gerät
still als Vorlage verwendet. Ein Tagesprofil kann ausdrücklich von einem der
Raumgeräte übernommen oder neu angelegt werden.

Der Wochenplan verwendet eine Stufenkurve und präzise Eingabezeilen:

- Der erste Abschnitt beginnt fest um 00:00; der letzte reicht bis 24:00.
- Uhrzeiten werden im 24-Stunden-Format eingegeben (`0630` wird zu `06:30`).
- MAX! erlaubt fünf Minuten Zeitraster, halbe Temperaturgrade und höchstens
  13 Temperaturabschnitte pro Tag.
- **Tag auf alle Tage kopieren** ersetzt nach Bestätigung die sieben Tagesentwürfe.
  Erst Speichern startet die Übertragung.

**Verwerfen** verwirft ausschließlich ungespeicherte Änderungen. Vorhandene
Entwürfe aus den bisherigen Geräte-Entitäten können nach Rückfrage ebenfalls
verworfen werden. Eingereihte Aufträge und bestätigte Werte bleiben erhalten.
Ein Raumwechsel mit Änderungen fragt nach; Wiederverbindung erhält den offenen
Entwurf. Ein vollständiges Neuladen der Browserseite verwirft lokale Entwürfe
(nach dem üblichen Browserhinweis). Akzeptierte Aufträge bleiben gespeichert.
Kopieren der gesamten Konfiguration auf andere Räume ist noch nicht enthalten.

### Sperren, Konflikte und Teilübertragung

Die vier Temperaturparameter werden zusammen in einem Funkpaket übertragen und
bilden daher einen Sperrblock; der gesamte Wochenplan bildet den zweiten.
Während ein Block eingereiht ist oder übertragen wird, bleibt er lesbar und wird
für weitere Änderungen gesperrt. Andere Räume und der jeweils freie Block bleiben
bedienbar. Die Sperre gilt auch für die bisherigen Konfigurationsaktionen und
Geräteentitäten. Bei einem Fehler mit ausstehendem Retry bleibt der Block gesperrt.

Eine Revision verhindert, dass ein zweiter Browser oder eine geänderte
Raumzuordnung einen veralteten Entwurf unbemerkt speichert. Bei Konflikten bleibt
der Entwurf sichtbar; Verwerfen lädt den aktuellen Stand. Mehrfachklicks und
wiederholte Anfragen mit derselben Auftrags-ID erzeugen keine weiteren Aufträge.

**Eingereiht ist nicht bestätigt.** Unter „Geräte und Übertragungsfortschritt“
stehen Status, bestätigte Paketanzahl und Fehler pro Gerät. Erst ACKs bestätigen
übertragene Werte. Ein Wochenplantag gilt erst nach seinen erforderlichen
Teilpaketen als bestätigt. Teilübertragene Tage werden nicht als vollständiges
Profil angeboten. Ein Auftrag kann hier oder in der Queue-Karte ausdrücklich
abgebrochen werden: Eine laufende Übertragung endet zuerst; bestätigte Teile
bleiben am Gerät. Ein Abbruch ist kein Zurücksetzen der Hardware.

Aufträge laufen in der bestehenden persistenten Queue und werden nach Neustart
fortgesetzt. Sperren ergeben sich aus dieser Queue und laufenden Befehlen, nicht
aus Browser-Timern. Die Oberfläche lädt nach Reconnect den aktuellen Stand und
erhält Statusänderungen ohne regelmäßiges Polling. Es gibt kein echtes vollständiges
Konfigurations-Readback: „bestätigt“ bezeichnet einen ACK-bestätigten Schreibvorgang.

### Öffentliche Schnittstellen

- `cul_max.get_room_config`: Räume, gespeicherte und vorgemerkte Werte, Revisionen,
  Gerätestatus und Sperren. Antwort unter `rooms`.
- `cul_max.save_room_config`: `area_id`, `changes`, `expected_revision`, `operation_id`.
  Antwort `status: accepted` oder `unchanged`, dazu `operation_id` und `job_ids`.
- `cul_max.discard_room_config`: `area_id`, `expected_revision`; entfernt nur
  ungespeicherte Geräteentwürfe.
- WebSocket `cul_max/room_config/subscribe`: initiale Raumübersicht und zusammengefasste
  Aktualisierungen. Die übliche HA-Abmeldung entfernt das Abonnement.

Alle Schnittstellen sind auf Administratoren begrenzt. `changes` enthält nur
geänderte Schlüssel: `comfort_temperature`, `eco_temperature`,
`window_open_temperature`, `window_open_duration` und optional `week_profile` mit
Tagesnamen `monday` bis `sunday` und Profilstrings wie `17,06:00,21,22:00,17`.
`expected_revision` stammt unverändert aus der Raumübersicht. Bei einer Wiederholung
nach Verbindungsverlust müssen Auftrags-ID und Nutzdaten unverändert bleiben.
