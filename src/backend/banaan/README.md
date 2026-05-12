# Banaan Rooster
Tool to create the "Banaan Schema" for 't Garijp

## Doel
Het doel is om de bananenschema automatisch te maken. Dit is een rooster van indelingen van kinderen, de tijden van de banaanen en de instructeur indelingen over de hele dag. 

## Achtergrond
Er is een groep cursisten. Elke cursist heeft aangegeven om wel of niet te gaan bananen. Elke cursist hoort bij een instructeur, en elke instructeur hoort bij een discipline. De disciplines zijn Jeugdzeil (jz), zwaardboot (zb), windsurf (ws), catamaran (cat) en kielboot (kb)

## Cost function
De te minimaliseren kosten zijn de aantal bananen die gebruikt moeten worden. Daarnaast moet elk groepje zo heel mogelijk worden gehouden, het liefst worden cursisten zo min mogelijk omgeplaatst. Voorkeur wordt gegeven aan dat cursisten met vrienden kunnen zijn.

## Constraints
De banaan passen 6 cursisten op. De cursisten moeten naar het eiland gebracht worden door een instructeur. Een instructeur kan een variable aantal cursisten vervoeren, afhankelijk van discipline. Elke cursist moet altijd bij een instructeur zijn van hun eigen discipline als ze niet mee gaan, als ze wel bananen hoeft het niet per se. Volgorde van de dag: JZ, Zb/Ws/Cat, Kb. De banaan duurt 15 minuten, een groepje moet 15 minuten van tevoren aanwezig zijn en vervoer van en naar het vaargebied kost 15 minuten per kant op. Er kan tussen 10:30 en 4 gebanaand worden, maar eerder beginnen is beter. Alle bananen moeten aaneensluitend zijn. Disciplines moeten aaneensluitend zijn. Een kind kan een vriend opgeven, die wordt bij die vriend ingedeeld.

### Cross-discipline dekking
Instructeurs mogen de kinderen van een andere discipline opvangen (niet banaan kinderen), maar dit heeft niet de voorkeur. De volgende combinaties zijn toegestaan:
- **JZ ↔ ZB**: Een JZ-instructeur kan ZB-kinderen opvangen en andersom
- **ZB ↔ CAT**: Een ZB-instructeur kan CAT-kinderen opvangen en andersom

Geen andere cross-discipline combinaties zijn mogelijk. Dit betekent dat bijv. een enkele ZB-instructeur toch kan vervoeren, omdat een JZ- of CAT-instructeur de achterblijvende ZB-kinderen kan opvangen.

