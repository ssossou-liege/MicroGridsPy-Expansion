"""What the interface says, in each language it says it.

English is the default because the people who will run this work across borders and hand
results to lenders and ministries that read English. French is kept complete rather than
partial: the first users are in francophone West Africa, and a half-translated interface is
worse than an untranslated one — it makes a reader wonder which half they are looking at.

Every string the page or the form shows lives here, keyed once. A key with no entry falls
back to English rather than to its own name, so a missed translation reads as English and
not as debug output.
"""
from __future__ import annotations

LANGUAGES: dict[str, str] = {"en": "English", "fr": "Français"}
DEFAULT = "en"

#: Keyed strings. The English entry is authoritative; French follows it.
STRINGS: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------- chrome
    "app.tagline": {"en": "Certified sizing", "fr": "Dimensionnement certifié"},
    "nav.uses": {"en": "Uses and archetypes", "fr": "Usages et archétypes"},
    "nav.assumptions": {"en": "Assumptions", "fr": "Hypothèses"},

    "page.uses.title": {"en": "Uses and archetypes", "fr": "Usages et archétypes"},
    "page.uses.lead": {
        "en": "The consumption behaviours the demand is built on. Check them against what "
              "you know of the community, and correct them if need be.",
        "fr": "Les comportements de consommation sur lesquels la demande est bâtie. "
              "Vérifiez-les contre ce que vous connaissez de la communauté, et corrigez-les "
              "si besoin."},
    "page.assumptions.title": {"en": "Assumptions", "fr": "Hypothèses"},
    "page.assumptions.lead": {
        "en": "Prices, service lives and control. Every value carries a default whose source "
              "is shown, and which you may change.",
        "fr": "Prix, durées de vie et conduite. Tout porte une valeur par défaut dont la "
              "source est indiquée, et que vous pouvez modifier."},

    # ---------------------------------------------------------------- actions
    "action.stop": {"en": "Stop", "fr": "Arrêter"},
    "action.delete": {"en": "Delete", "fr": "Supprimer"},
    "action.open": {"en": "Open…", "fr": "Ouvrir…"},
    "action.export_csv": {"en": "Export as CSV", "fr": "Exporter en CSV"},
    "action.export_json": {"en": "Export as JSON", "fr": "Exporter en JSON"},
    "action.print": {"en": "Printable report", "fr": "Rapport imprimable"},
    "action.apply": {"en": "Apply to this site", "fr": "Appliquer à ce site"},
    "action.reset": {"en": "Back to calibrated values",
                     "fr": "Revenir aux valeurs calibrées"},
    "action.save_site": {"en": "Save the community", "fr": "Enregistrer la communauté"},
    "action.fetch_resource": {"en": "Fetch the meteorological series",
                              "fr": "Obtenir la série météorologique"},
    "state.ready": {"en": "Ready.", "fr": "Prêt."},
    "state.saved": {"en": "Project saved.", "fr": "Projet enregistré."},
    "state.applied": {"en": "Archetypes applied. The next sizing will use them.",
                      "fr": "Archétypes appliqués. Le prochain dimensionnement en tiendra "
                            "compte."},

    # ---------------------------------------------------------------- community
    "site.new.name": {"en": "New community", "fr": "Nouvelle communauté"},
    "state.site_failed": {"en": "The site could not be saved.",
                          "fr": "Le site n'a pas pu être enregistré."},
    "state.need_name": {"en": "The community needs a name.",
                        "fr": "La communauté a besoin d'un nom."},
    "state.need_point": {
        "en": "Place the community on the map, or type its coordinates.",
        "fr": "Posez la communauté sur la carte, ou saisissez ses coordonnées."},
    "state.need_households": {
        "en": "No households to connect: enter the count from the field survey.",
        "fr": "Aucun foyer à raccorder : saisissez le nombre relevé à l'enquête."},
    "site.name": {"en": "Community name", "fr": "Nom de la communauté"},
    "site.households": {"en": "Households to connect", "fr": "Foyers à raccorder"},
    "site.households.hint": {
        "en": "The household count by type, as the field survey recorded it. Count the whole "
              "community and not a sample.",
        "fr": "Le nombre de foyers par type, tel que l'enquête de terrain l'a relevé. "
              "Comptez la communauté entière et non un échantillon."},
    "site.productive": {"en": "Productive uses", "fr": "Activités productives"},
    "site.productive.hint": {
        "en": "Which activities the community has, and how many of each. They decide whether "
              "the plant is daytime-heavy or evening-heavy. Leave every count at zero if you "
              "do not know: the mix is then drawn from the reference villages.",
        "fr": "Quelles activités la communauté abrite, et combien de chacune. Ce sont elles "
              "qui décident si la centrale est diurne ou vespérale. Laissez tous les "
              "comptes à zéro si vous ne savez pas : la composition sera alors tirée des "
              "villages de référence."},
    "site.utc": {"en": "Offset from universal time", "fr": "Décalage horaire"},
    "site.where": {"en": "Where it is", "fr": "Où se trouve-t-il"},
    "site.latitude": {"en": "Latitude", "fr": "Latitude"},
    "site.longitude": {"en": "Longitude", "fr": "Longitude"},
    "site.map.hint": {
        "en": "Click the map to place the point, or type the coordinates and check they fall "
              "on your site. The background map needs a connection; the coordinates do not.",
        "fr": "Cliquez sur la carte pour poser le point, ou saisissez les coordonnées et "
              "vérifiez qu'elles tombent bien sur votre site. Le fond de carte demande une "
              "connexion ; les coordonnées se saisissent sans."},
    "site.series.have": {"en": "Series available", "fr": "Série disponible"},
    "site.series.none": {"en": "No series", "fr": "Aucune série"},
    "site.series.hint": {
        "en": "Without a meteorological series the sizing cannot start. It downloads once per "
              "site from a public reanalysis and needs a connection.",
        "fr": "Sans série météorologique le dimensionnement ne peut pas démarrer. Elle se "
              "télécharge une fois par site depuis une réanalyse publique et demande une "
              "connexion."},
    "site.card": {"en": "Site", "fr": "Site"},

    # ---------------------------------------------------------------- archetypes
    "arch.origin": {"en": "Where these behaviours come from",
                    "fr": "D'où viennent ces comportements"},
    "arch.adjusted": {"en": "These values have been adjusted for this site.",
                      "fr": "Ces valeurs ont été ajustées pour ce site."},
    "arch.title": {"en": "The four household archetypes",
                   "fr": "Les quatre archétypes de ménage"},
    "arch.behaviour": {"en": "Behaviour", "fr": "Comportement"},
    "arch.energy": {"en": "Energy kWh/day", "fr": "Énergie kWh/jour"},
    "arch.peak": {"en": "Peak W", "fr": "Pointe W"},
    "arch.load_factor": {"en": "Load factor", "fr": "Facteur de charge"},
    "arch.share": {"en": "% of households observed", "fr": "% des ménages observés"},
    "arch.records": {"en": "records", "fr": "relevés"},
    "arch.weak": {"en": "thinly supported", "fr": "peu étayé"},
    "arch.hint": {
        "en": "Changing an archetype's energy or peak really moves the simulated demand: the "
              "two factors that reconcile the appliance sets to these targets are recomputed, "
              "and the sizing accounts for it. The load factor is reported for information "
              "and is not set separately.",
        "fr": "Modifier l'énergie ou la pointe d'un archétype déplace réellement la demande "
              "simulée : les deux facteurs qui accordent les parcs d'appareils à ces cibles "
              "sont recalculés, et le dimensionnement en tient compte. Le facteur de charge "
              "est rapporté pour information et ne se règle pas séparément."},
    "arch.note": {
        "en": "Calibrated on 1 818 household-months of quarter-hourly records from 141 "
              "households in two Beninese villages. To be checked before use on a community "
              "whose uses, tariff or hours differ.",
        "fr": "Calibrés sur 1 818 couples ménage-mois relevés au pas quart-horaire chez 141 "
              "ménages de deux villages béninois. À vérifier avant tout emploi sur une "
              "communauté dont les usages, le tarif ou les horaires diffèrent."},

    # ---------------------------------------------------------------- results
    "res.plant": {"en": "Certified plant", "fr": "Parc certifié"},
    "res.pv": {"en": "Photovoltaic", "fr": "Photovoltaïque"},
    "res.storage": {"en": "Storage", "fr": "Stockage"},
    "res.conversion": {"en": "Conversion", "fr": "Conversion"},
    "res.generator": {"en": "Generating set", "fr": "Groupe"},
    "res.battery_bus": {"en": "battery bus", "fr": "bus batterie"},
    "res.load_bus": {"en": "load bus", "fr": "bus charge"},
    "res.proven": {"en": "Optimality proven by exhaustion",
                   "fr": "Optimalité prouvée par épuisement"},
    "res.unproven": {"en": "Search incomplete", "fr": "Recherche incomplète"},
    "res.cost_title": {"en": "What it costs", "fr": "Ce que cela coûte"},
    "res.lcoe": {"en": "Levelised cost", "fr": "Coût actualisé"},
    "res.annual": {"en": "Annualised cost", "fr": "Coût annualisé"},
    "res.subsidy": {"en": "Subsidy", "fr": "Subvention"},
    "res.subsidy.none": {"en": "none", "fr": "aucune"},
    "res.subsidy.met": {"en": "the tariff is met", "fr": "le tarif est atteint"},
    "res.target": {"en": "target tariff", "fr": "tarif visé"},
    "res.gap": {"en": "Dispatch gap", "fr": "Écart de dispatch"},
    "res.week": {"en": "The most demanding week", "fr": "La semaine la plus sollicitée"},
    "res.week.hint": {
        "en": "Seven days taken where the generating set runs most, a plant being judged on "
              "its worst stretch. The stacked area is what serves the load hour by hour; the "
              "solid line is demand, the dashed one the state of charge.",
        "fr": "Sept jours pris là où le groupe tourne le plus, une installation se jugeant "
              "sur sa pire période. L'aire empilée est ce qui sert la charge heure par "
              "heure ; le trait plein est la demande, le pointillé l'état de charge."},
    "res.year": {"en": "What the plant produces over a year",
                 "fr": "Ce que la centrale produit sur l'année"},
    "res.how": {"en": "How the certificate was obtained",
                "fr": "Comment le certificat a été obtenu"},
    "res.quantity": {"en": "Quantity", "fr": "Grandeur"},
    "res.value": {"en": "Value", "fr": "Valeur"},
    "res.lattice": {"en": "Sizings in the admissible set",
                    "fr": "Dimensionnements de l'ensemble admissible"},
    "res.pruned": {"en": "Excluded by a bound, without simulation",
                   "fr": "Écartés par une borne, sans simulation"},
    "res.simulated": {"en": "Evaluated by simulation", "fr": "Évalués par simulation"},
    "res.relaxations": {"en": "Relaxed programmes solved",
                        "fr": "Programmes relaxés résolus"},
    "res.seconds": {"en": "Duration", "fr": "Durée"},
    "res.coverage": {
        "en": "Every sizing of the set was either evaluated or excluded by a bound whose "
              "validity is proven. None was left aside.",
        "fr": "Chaque dimensionnement de l'ensemble a été soit évalué, soit écarté par une "
              "borne dont la validité est démontrée. Aucun n'a été laissé de côté."},

    # ---------------------------------------------------------------- finance
    "fin.title": {"en": "What the project returns", "fr": "Ce que le projet rend"},
    "fin.bare_irr": {"en": "{rate} once the residual value is struck out",
                     "fr": "{rate} une fois la valeur résiduelle retirée"},
    "fin.salvage": {"en": "Residual value", "fr": "Valeur résiduelle"},
    "fin.beyond_plant": {
        "en": "Includes {n} of network, connections, civil works and development.",
        "fr": "Comprend {n} de réseau, branchements, génie civil et développement."},
    "fin.plant_only": {
        "en": "This is the power plant alone. The distribution network, the connections, "
              "the civil works and the development are not priced, and they are about half "
              "of what a mini-grid costs. Enter them under \u201cBeyond the plant\u201d.",
        "fr": "Ceci n'est que la centrale. Le réseau de distribution, les branchements, le "
              "génie civil et le développement ne sont pas chiffrés, et ils représentent "
              "environ la moitié du coût d'un mini-réseau. Saisissez-les sous "
              "\u00ab\u202fAu-delà de la centrale\u202f\u00bb."},
    "res.battery_life": {"en": "replaced every {n} years",
                         "fr": "remplacé tous les {n} ans"},
    "res.ceiling_binds": {
        "en": "The optimum sits exactly on a ceiling ({which}), so a single sourced ratio "
              "decides it as much as anything entered here. Worth a sensitivity.",
        "fr": "L'optimum se pose exactement sur un plafond ({which}) : un seul ratio "
              "sourcé le décide autant que ce qui a été saisi ici. Mérite une "
              "sensibilité."},
    "res.ceiling.dc_ratio": {"en": "array per kW on the battery bus",
                             "fr": "champ par kW sur le bus batterie"},
    "res.ceiling.ac_ratio": {"en": "array per kW on the load bus",
                             "fr": "champ par kW sur le bus charge"},

    "unit.per_year": {"en": "/yr", "fr": "/an"},
    "fin.irr": {"en": "Internal rate of return", "fr": "Taux de rentabilité"},
    "fin.irr.none": {"en": "none", "fr": "aucun"},
    "fin.irr.never": {"en": "revenue never covers the capital",
                      "fr": "les recettes ne couvrent jamais le capital"},
    "fin.payback": {"en": "Payback", "fr": "Retour sur investissement"},
    "fin.payback.never": {"en": "never", "fr": "jamais"},
    "fin.npv": {"en": "Net present value", "fr": "Valeur actuelle nette"},
    "fin.capital": {"en": "Initial capital", "fr": "Capital initial"},
    "fin.year": {"en": "Year", "fr": "Année"},
    "fin.investment": {"en": "Investment", "fr": "Investissement"},
    "fin.operating": {"en": "Operating", "fr": "Exploitation"},
    "fin.revenue": {"en": "Revenue", "fr": "Recettes"},
    "fin.net": {"en": "Net flow", "fr": "Flux net"},
    "fin.hint": {
        "en": "Pre-tax and unlevered: a project that does not clear the bar here will not "
              "clear it afterwards. Years carrying an equipment replacement are included.",
        "fr": "Avant impôt et sans effet de levier : un projet qui ne passe pas la barre ici "
              "ne la passera pas après. Les années portant un remplacement d'équipement sont "
              "incluses."},
    "fin.unsubsidised": {"en": "Without the subsidy the rate would be {rate}.",
                         "fr": "Sans la subvention, le taux serait de {rate}."},
    "fin.replacements": {"en": "Years carrying an equipment replacement are included.",
                         "fr": "Les années portant un remplacement d'équipement sont incluses."},
    "fin.years": {"en": "years", "fr": "ans"},

    # ---------------------------------------------------------------- plan
    "plan.future": {"en": "What the future will decide", "fr": "Ce que l'avenir décidera"},
    "plan.branch": {"en": "Branch at year", "fr": "Branche à l'année"},
    "plan.probability": {"en": "Probability", "fr": "Probabilité"},
    "plan.energy": {"en": "Energy to serve", "fr": "Énergie à servir"},
    "plan.enlarge": {"en": "enlarge", "fr": "agrandir"},
    "plan.hold": {"en": "add nothing", "fr": "ne rien ajouter"},
    "plan.grid_here": {"en": "grid arrived", "fr": "réseau arrivé"},
    "plan.tree": {"en": "The tree has {nodes} nodes and {leaves} leaves. Only the first line "
                        "is committed; the rest is decided when the uncertainty lifts.",
                  "fr": "L'arbre compte {nodes} nœuds et {leaves} feuilles. Seule la première "
                        "ligne est engagée ; les suivantes se décideront quand l'incertitude "
                        "se sera levée."},
    "plan.gap": {"en": "Dispatch gap", "fr": "Écart de dispatch"},
    "plan.cost": {"en": "What the plan costs", "fr": "Ce que le plan coûte"},
    "plan.expected_lcoe": {"en": "Expected levelised cost",
                           "fr": "Coût actualisé attendu"},
    "plan.expected_cost": {"en": "Expected cost", "fr": "Coût attendu"},
    "plan.evaluations": {"en": "Plans evaluated", "fr": "Évaluations de plans"},
    "plan.upper": {
        "en": "This gap is an upper bound: on the tree the plan comes from a descent and not "
              "from a certification by exhaustion.",
        "fr": "Cet écart est un majorant : sur l'arbre, le plan provient d'une descente et "
              "non d'une certification par épuisement."},

    # ---------------------------------------------------------------- projects
    # ---------------------------------------------------------- printed report
    "print.title": {"en": "Certified sizing", "fr": "Dimensionnement certifié"},
    "print.issued": {"en": "Issued {date}", "fr": "Édité le {date}"},
    "print.amounts": {"en": "Amounts in {code}", "fr": "Montants en {code}"},
    "print.behaviour": {"en": "Consumption behaviour:", "fr": "Comportements de consommation :"},
    "print.arch.adjusted": {"en": "archetypes adjusted for this site.",
                            "fr": "archétypes ajustés pour ce site."},
    "print.arch.shipped": {"en": "archetypes as shipped, not adjusted.",
                           "fr": "archétypes livrés, non ajustés."},

    # ---------------------------------------------------------------- the front door
    "home.title": {"en": "What should this community build?",
                   "fr": "Que faut-il construire pour cette communauté ?"},
    "home.lead": {
        "en": "Describe a village, and the tool returns the plant to buy this year — array, "
              "storage, conversion, generating set — sized for every way its demand may "
              "grow, with the tariff that plant implies and proof that no cheaper one exists.",
        "fr": "Décrivez un village : l'outil renvoie la centrale à acheter cette année — "
              "champ, stockage, conversion, groupe électrogène — dimensionnée pour toutes "
              "les manières dont sa demande peut croître, avec le tarif qu'elle implique et "
              "la preuve qu'il n'en existe pas de moins chère."},
    "home.new": {"en": "Create a new project", "fr": "Créer un nouveau projet"},
    "home.new.hint": {"en": "Start from a community you describe yourself.",
                      "fr": "Partir d'une communauté que vous décrivez vous-même."},
    "home.new.asks": {
        "en": "A name, a point on the map, the households and the productive uses. Four "
              "pages, and the last one is the answer.",
        "fr": "Un nom, un point sur la carte, les foyers et les activités productives. "
              "Quatre pages, dont la dernière est la réponse."},
    "home.households": {"en": "households", "fr": "foyers"},
    "home.open": {"en": "Open a project", "fr": "Ouvrir un projet"},
    "home.open.hint": {"en": "Pick up a study saved on this machine.",
                       "fr": "Reprendre une étude enregistrée sur cette machine."},
    "home.open.none": {"en": "Nothing saved yet.", "fr": "Rien d'enregistré pour l'instant."},
    "home.open.answered": {"en": "answered", "fr": "répondue"},
    "home.test": {"en": "Try it on a real village", "fr": "L'essayer sur un vrai village"},
    "home.test.hint": {
        "en": "Two surveyed communities in northern Benin, shipped whole — households, "
              "enterprises and weather. A study runs on them with no network.",
        "fr": "Deux communautés enquêtées du nord du Bénin, livrées entières — foyers, "
              "entreprises et météorologie. Une étude s'y déroule sans connexion."},
    "home.sample.title": {"en": "What comes back", "fr": "Ce que l'outil renvoie"},
    "home.sample.note": {
        "en": "Shown here as an illustration. The figures on your project are computed from "
              "your own description.",
        "fr": "Montré ici à titre d'illustration. Les chiffres de votre projet sont calculés "
              "à partir de votre propre description."},
    "home.sample.plant": {"en": "The plant to build", "fr": "La centrale à construire"},
    "home.sample.dispatch": {"en": "How it runs, hour by hour",
                             "fr": "Sa conduite, heure par heure"},
    "home.sample.tariff": {"en": "What it costs a customer",
                           "fr": "Ce qu'elle coûte à un abonné"},
    "home.art.alt": {"en": "A solar mini-grid at the edge of a village",
                     "fr": "Un mini-réseau solaire en lisière de village"},
    "home.credit": {
        "en": "Built on MicroGridsPy. Archetypes calibrated on metered consumption in "
              "northern Benin.",
        "fr": "Bâti sur MicroGridsPy. Archétypes calibrés sur des consommations relevées au "
              "compteur dans le nord du Bénin."},

    # ---------------------------------------------------------------- moving through the pages
    "wiz.next": {"en": "Next page", "fr": "Page suivante"},
    "wiz.back": {"en": "Previous page", "fr": "Page précédente"},
    "wiz.step": {"en": "Step {n} of {total}", "fr": "Étape {n} sur {total}"},
    "wiz.home": {"en": "Home", "fr": "Accueil"},
    "wiz.info": {"en": "What this is", "fr": "De quoi il s'agit"},

    # ---------------------------------------------------------------- the new project page
    "page.project.title": {"en": "A new project", "fr": "Un nouveau projet"},
    "page.project.lead": {
        "en": "Name the study, then describe the community it is for. Everything here comes "
              "from a field survey; nothing has to be guessed at a desk.",
        "fr": "Nommez l'étude, puis décrivez la communauté qu'elle vise. Tout ce qui est "
              "demandé ici provient d'une enquête de terrain ; rien ne se devine au bureau."},
    "proj.name": {"en": "Project name", "fr": "Nom du projet"},
    "proj.name.hint": {
        "en": "How this study will be listed when you come back to it. One community may "
              "carry several, under different assumptions.",
        "fr": "Sous quel nom cette étude sera listée à votre retour. Une même communauté "
              "peut en porter plusieurs, sous des hypothèses différentes."},
    "site.name.hint": {
        "en": "The village or hamlet to be electrified, as it is known locally.",
        "fr": "Le village ou le hameau à électrifier, sous son nom d'usage local."},
    "site.utc.derived": {
        "en": "Time zone taken from the longitude: UTC{offset}, where solar noon falls at "
              "{solar} local time.",
        "fr": "Fuseau horaire déduit de la longitude : UTC{offset}, où le midi solaire tombe "
              "à {solar} heure locale."},
    "site.utc.adjust": {"en": "Adjust", "fr": "Corriger"},
    "site.utc.adjust.hint": {
        "en": "Several countries keep a zone an hour or more from their sun, and an hour's "
              "error here displaces generation against consumption by an hour — which is "
              "what a storage sizing is most sensitive to.",
        "fr": "Plusieurs pays gardent un fuseau éloigné d'une heure ou plus de leur soleil, "
              "et une heure d'erreur ici décale la production d'une heure par rapport à la "
              "consommation — ce à quoi un dimensionnement de stockage est le plus sensible."},
    "pue.count": {"en": "how many", "fr": "combien"},
    "pue.none": {
        "en": "No activity selected: the mix will be drawn from the reference villages.",
        "fr": "Aucune activité sélectionnée : la composition sera tirée des villages de "
              "référence."},
    "pue.total": {"en": "{n} productive customers in all",
                  "fr": "{n} clients productifs au total"},

    # ---------------------------------------------------------------- activity classes
    "pue.refrigeration": {"en": "Refrigeration and ice",
                          "fr": "Réfrigération et glace"},
    "pue.refrigeration.hint": {
        "en": "Ice makers, drink coolers, fishmongers, anything held cold. It runs around "
              "the clock, which is why it weighs on storage more than its power suggests.",
        "fr": "Fabriques de glace, réfrigérateurs à boissons, poissonneries, tout ce qui se "
              "garde au froid. Cela tourne jour et nuit, et pèse donc sur le stockage plus "
              "que sa puissance ne le laisse croire."},
    "pue.milling": {"en": "Milling", "fr": "Mouture"},
    "pue.milling.hint": {
        "en": "Maize and cassava mills. Several kilowatts in short bursts, concentrated in "
              "the morning and on market days.",
        "fr": "Moulins à maïs et à manioc. Plusieurs kilowatts par à-coups brefs, "
              "concentrés le matin et les jours de marché."},
    "pue.incubation": {"en": "Egg incubation", "fr": "Incubation d'œufs"},
    "pue.incubation.hint": {
        "en": "Incubators and brooders. A modest load that cannot be interrupted, held for "
              "weeks at a time, day and night.",
        "fr": "Couveuses et éleveuses. Une charge modeste mais qu'on ne peut interrompre, "
              "maintenue des semaines durant, jour et nuit."},
    "pue.tailoring": {"en": "Tailoring", "fr": "Couture"},
    "pue.tailoring.hint": {
        "en": "Sewing and embroidery workshops. Daylight hours, modest power, and usually "
              "several of them in a village.",
        "fr": "Ateliers de couture et de broderie. Aux heures du jour, puissance modeste, et "
              "généralement plusieurs par village."},
    "pue.sawmill": {"en": "Sawmill", "fr": "Scierie"},
    "pue.sawmill.hint": {
        "en": "Powered sawing. The heaviest single load a village grid carries, and the one "
              "that usually sets its peak; it takes three phases.",
        "fr": "Sciage mécanisé. La charge unitaire la plus lourde d'un réseau villageois, "
              "et celle qui en fixe généralement la pointe ; elle demande le triphasé."},
    "pue.small_trade": {"en": "Shops and small trade", "fr": "Boutiques et petit commerce"},
    "pue.small_trade.hint": {
        "en": "Shops, phone charging, bars, hairdressers. Small one by one, and together the "
              "evening peak; the survey passed over them in favour of the large consumers, "
              "so their profile is measured as a class rather than one by one.",
        "fr": "Boutiques, recharge de téléphones, buvettes, coiffure. Faibles une à une, "
              "elles forment ensemble la pointe du soir ; l'enquête les a laissées de côté "
              "au profit des gros consommateurs, et leur profil est donc mesuré en classe "
              "et non un à un."},

    # ---------------------------------------------------------------- the sizing
    "action.size": {"en": "Size the plant", "fr": "Dimensionner la centrale"},
    "job.size": {"en": "Sizing — {site}", "fr": "Dimensionnement — {site}"},
    "page.sizing.title": {"en": "The sizing", "fr": "Le dimensionnement"},
    "page.sizing.lead": {
        "en": "What to buy this year, sized over every trajectory the demand may take, and "
              "what that plant costs to own and to run.",
        "fr": "Ce qu'il faut acheter cette année, dimensionné sur toutes les trajectoires "
              "que la demande peut suivre, et ce que cette centrale coûte à posséder et à "
              "faire tourner."},
    # ---------------------------------------------------------------- the tree drawn
    "tree.title": {"en": "The plan over every future",
                   "fr": "Le plan sur tous les avenirs"},
    "tree.alt": {
        "en": "The scenario tree, one column per milestone year, with the plant held at "
              "each node",
        "fr": "L'arbre de scénarios, une colonne par année jalon, avec la centrale tenue "
              "à chaque nœud"},
    "tree.lead": {
        "en": "Only the leftmost plant is bought now. Everything to the right of it is a "
              "future the plan is ready for, and what is added there is added only if that "
              "future arrives. The thicker the line, the likelier the branch.",
        "fr": "Seule la centrale la plus à gauche s'achète maintenant. Tout ce qui est à sa "
              "droite est un avenir auquel le plan est prêt, et ce qui s'y ajoute ne "
              "s'ajoute que si cet avenir survient. Plus le trait est épais, plus la "
              "branche est probable."},
    "tree.grows": {"en": "grows on the previous milestone",
                   "fr": "s'agrandit par rapport à l'échéance précédente"},
    "tree.holds": {"en": "adds nothing", "fr": "n'ajoute rien"},
    "tree.year": {"en": "Year", "fr": "Année"},
    "tree.stage": {"en": "Stage", "fr": "Étape"},
    "tree.node": {"en": "Node", "fr": "Nœud"},
    "tree.error": {
        "en": "Mean compression error of each milestone: {list}. It measures what the "
              "reduction to representative futures has lost.",
        "fr": "Erreur moyenne de compression de chaque échéance : {list}. Elle mesure ce "
              "que la réduction en avenirs représentatifs a perdu."},

    "sizing.build": {"en": "Build this year", "fr": "À construire cette année"},
    "sizing.over_tree": {
        "en": "Chosen over {leaves} demand trajectories on {nodes} decision points.",
        "fr": "Choisie sur {leaves} trajectoires de demande et {nodes} points de décision."},
    "sizing.reference": {"en": "Against the demand as it is today",
                           "fr": "Face à la demande d'aujourd'hui"},
    "sizing.reference.hint": {
        "en": "The cheapest plant for the first year alone, found by examining every "
              "admissible design. It is sized for the demand as it stands; the plant above "
              "is sized knowing that demand will move and that more can be added at the "
              "next milestone. Where the plant above is larger, the difference is what "
              "providing for growth costs; where it is smaller, the difference is what the "
              "option to expand is worth — capacity that need not be bought until the "
              "uncertainty has lifted.",
        "fr": "La centrale la moins chère pour la seule première année, trouvée en "
              "examinant tous les dimensionnements admissibles. Elle est dimensionnée pour "
              "la demande telle quelle ; la précédente l'est en sachant que la demande "
              "bougera et qu'on pourra ajouter à la prochaine échéance. Là où la "
              "précédente est plus grande, l'écart est le prix de la croissance anticipée ; "
              "là où elle est plus petite, l'écart est ce que vaut l'option d'étendre — une "
              "capacité qu'il est inutile d'acheter avant que l'incertitude ne se lève."},
    "sizing.proven.yes": {"en": "Proven optimal", "fr": "Optimalité prouvée"},
    "sizing.proven.no": {"en": "Best found, not yet proven",
                           "fr": "Meilleure trouvée, non encore prouvée"},
    "sizing.proven.hint": {
        "en": "The first year is certified by examining every design the bounds admit. The "
              "year-0 decision over the whole tree comes from a coordinated descent, which "
              "no bound has yet closed — it is the best found and not the proven best.",
        "fr": "La première année est certifiée en examinant tous les dimensionnements que "
              "les bornes admettent. La décision d'année zéro sur l'arbre entier provient "
              "d'une descente coordonnée, qu'aucune borne n'a encore refermée — c'est la "
              "meilleure trouvée et non la meilleure prouvée."},

    "csv.section.sizing": {"en": "BUILD THIS YEAR", "fr": "À CONSTRUIRE CETTE ANNÉE"},
    "csv.section.reference": {"en": "REFERENCE YEAR, CERTIFIED",
                              "fr": "ANNÉE DE RÉFÉRENCE, CERTIFIÉE"},

    "sizing.difference": {"en": "Difference", "fr": "Écart"},
    "sizing.same": {"en": "the same plant", "fr": "la même centrale"},
    "sizing.none.title": {"en": "Nothing sized yet",
                          "fr": "Rien de dimensionné pour l'instant"},
    "sizing.none.body": {
        "en": "Describe the community, check the behaviours its demand is built on, look "
              "over the assumptions, and the tool will return the plant to build.",
        "fr": "Décrivez la communauté, vérifiez les comportements sur lesquels sa demande "
              "est bâtie, parcourez les hypothèses, et l'outil renverra la centrale à "
              "construire."},
    "sizing.again": {"en": "Compute it again", "fr": "Recalculer"},

    # One letter, and each language has its own: the axis of a week reads "D1" in English
    # and "J1" in French, and hard-coding either printed the other language's label.
    "chart.day": {"en": "D", "fr": "J"},

    "proj.placeholder": {"en": "Study name", "fr": "Nom de l'étude"},
    "proj.opened": {"en": "Project “{name}” opened.", "fr": "Projet « {name} » ouvert."},
    # ------------------------------------------------------- background work
    # The worker thread names its stage as a key: it does not know the reader's language,
    # and the reader may change it while the run is under way.
    # ------------------------------------------------------------ exports
    # A spreadsheet someone hands to a colleague, so its headers carry units and follow the
    # language the interface was read in.
    "csv.quantity": {"en": "Quantity", "fr": "Grandeur"},
    "csv.value": {"en": "Value", "fr": "Valeur"},
    "csv.site": {"en": "Community", "fr": "Localité"},
    "csv.trajectory": {"en": "Demand growth", "fr": "Croissance de la demande"},
    "csv.coupling": {"en": "Coupling", "fr": "Couplage"},
    "csv.pv_dc": {"en": "Photovoltaic, battery bus (kW)",
                  "fr": "Photovoltaïque bus batterie (kW)"},
    "csv.pv_ac": {"en": "Photovoltaic, load bus (kW)", "fr": "Photovoltaïque bus charge (kW)"},
    "csv.storage": {"en": "Storage (kWh)", "fr": "Stockage (kWh)"},
    "csv.inverter": {"en": "Conversion (kW)", "fr": "Conversion (kW)"},
    "csv.generator": {"en": "Generator (kW)", "fr": "Groupe (kW)"},
    "csv.z_rule": {"en": "Annualised cost under the controller ($/yr)",
                   "fr": "Coût annualisé sous automate ($/an)"},
    "csv.z_opt": {"en": "Annualised cost under anticipative dispatch ($/yr)",
                  "fr": "Coût annualisé sous dispatch anticipatif ($/an)"},
    "csv.gap": {"en": "Dispatch gap (%)", "fr": "Écart de dispatch (%)"},
    "csv.lcoe": {"en": "Levelised cost ($/kWh)", "fr": "Coût actualisé ($/kWh)"},
    "csv.npc": {"en": "Net present cost ($)", "fr": "Valeur actuelle nette ($)"},
    "csv.subsidy": {"en": "Subsidy (fraction)", "fr": "Subvention (fraction)"},
    "csv.served": {"en": "Energy served (kWh/yr)", "fr": "Énergie servie (kWh/an)"},
    "csv.unserved": {"en": "Unserved energy (kWh/yr)",
                     "fr": "Énergie non distribuée (kWh/an)"},
    "csv.proven": {"en": "Optimality proven", "fr": "Optimalité prouvée"},
    "csv.lattice": {"en": "Designs in the set", "fr": "Dimensionnements de l'ensemble"},
    "csv.pruned": {"en": "Excluded by a bound", "fr": "Écartés par une borne"},
    "csv.evaluated": {"en": "Evaluated by simulation", "fr": "Évalués par simulation"},
    "csv.seconds": {"en": "Runtime (s)", "fr": "Durée (s)"},
    "csv.nodes": {"en": "Nodes", "fr": "Nœuds"},
    "csv.leaves": {"en": "Leaves", "fr": "Feuilles"},
    "csv.exp_lcoe": {"en": "Expected levelised cost ($/kWh)",
                     "fr": "Coût actualisé attendu ($/kWh)"},
    "csv.exp_cost": {"en": "Expected cost ($)", "fr": "Coût attendu ($)"},
    "csv.node.node": {"en": "Node", "fr": "Nœud"},
    "csv.node.stage": {"en": "Stage", "fr": "Étape"},
    "csv.node.probability": {"en": "Probability", "fr": "Probabilité"},
    "csv.node.pv_dc": {"en": "PV battery bus (kW)", "fr": "PV bus batterie (kW)"},
    "csv.node.pv_ac": {"en": "PV load bus (kW)", "fr": "PV bus charge (kW)"},
    "csv.node.storage": {"en": "Storage (kWh)", "fr": "Stockage (kWh)"},
    "csv.node.inverter": {"en": "Conversion (kW)", "fr": "Conversion (kW)"},
    "csv.node.served": {"en": "Energy served (kWh)", "fr": "Énergie servie (kWh)"},
    "csv.node.unserved": {"en": "Unserved (kWh)", "fr": "Non distribuée (kWh)"},

    "job.resource": {"en": "Weather series — {site}", "fr": "Série météorologique — {site}"},
    "job.starting": {"en": "starting", "fr": "démarrage"},
    "job.build": {"en": "building demand and resource",
                  "fr": "construction de la demande et de la ressource"},
    "job.lattice": {"en": "bounding the admissible set",
                    "fr": "délimitation de l'ensemble admissible"},
    "job.certify": {"en": "certifying over {n} designs",
                    "fr": "certification sur {n} dimensionnements"},
    "job.sample": {"en": "sampling and reducing scenarios",
                   "fr": "tirage et réduction des scénarios"},
    "job.reduce": {"en": "compressing the time domain over {n} nodes",
                   "fr": "compression du domaine temporel sur {n} nœuds"},
    "job.solve": {"en": "solving the deterministic-equivalent programme",
                  "fr": "résolution du programme équivalent-déterministe"},
    "job.descend": {"en": "descending to the plan the controller prefers",
                    "fr": "descente vers le plan que l'automate préfère"},
    "job.reanalysis": {"en": "requesting the reanalysis for {lat}, {lon} — several minutes",
                       "fr": "demande de la réanalyse pour {lat}, {lon} — plusieurs minutes"},
    "job.store": {"en": "storing the series", "fr": "enregistrement de la série"},
    "job.stopping": {"en": "stop requested", "fr": "arrêt demandé"},
    "job.finished": {"en": "finished", "fr": "fini"},
    "job.interrupted": {"en": "interrupted", "fr": "interrompu"},
    "job.running": {"en": "running", "fr": "en cours"},
    "job.done": {"en": "done", "fr": "terminé"},
    "job.failed": {"en": "failed", "fr": "échoué"},
    "job.cancelled": {"en": "cancelled", "fr": "annulé"},

    "source.label": {"en": "Source", "fr": "Source"},
    "source.unsourced": {"en": "unsourced", "fr": "non sourcé"},

    # ---------------------------------------------------------------- form groups
    # ------------------------------------------------------------ choice values
    # The values themselves are the model's vocabulary and never change; these are only
    # how they read on the page. A value absent here is shown as it stands, which is what
    # a currency code or a solver name wants.
    "choice.slow": {"en": "slow", "fr": "lente"},
    "choice.central": {"en": "central", "fr": "centrale"},
    "choice.fast": {"en": "fast", "fr": "rapide"},
    "choice.yes": {"en": "yes", "fr": "oui"},
    "choice.no": {"en": "no", "fr": "non"},
    "choice.mixed": {"en": "divided array", "fr": "champ divisé"},
    "choice.dc": {"en": "battery bus only", "fr": "bus batterie seul"},
    "choice.ac": {"en": "load bus only", "fr": "bus charge seul"},
    "choice.auto": {"en": "let the tool choose", "fr": "laisser l'outil choisir"},

    "group.balance": {"en": "Beyond the plant", "fr": "Au-delà de la centrale"},
    "f.distribution": {"en": "Distribution network", "fr": "Réseau de distribution"},
    "f.distribution.hint": {
        "en": "Poles, conductor, earthing and the labour to string them. A lump sum: no "
              "per-kilometre figure carries from a compact village to a scattered one.",
        "fr": "Poteaux, conducteur, mise à la terre et main-d'œuvre de pose. Une somme "
              "forfaitaire : aucun prix au kilomètre ne se transporte d'un village "
              "groupé à un village dispersé."},
    "f.connection_1p": {"en": "Connection, single phase", "fr": "Branchement monophasé"},
    "f.connection_1p.hint": {
        "en": "Per household connected, meter included: service drop, board, meter, labour.",
        "fr": "Par foyer raccordé, compteur compris : branchement, coffret, compteur, pose."},
    "f.connection_3p": {"en": "Connection, three phase", "fr": "Branchement triphasé"},
    "f.connection_3p.hint": {
        "en": "Per productive customer. The mill, the welder and the sawmill take three "
              "phases, and they are counted from the productive units declared for the "
              "community.",
        "fr": "Par client productif. Le moulin, le soudeur et la scierie demandent trois "
              "phases, et leur nombre est celui des unités productives déclarées pour la "
              "communauté."},
    "f.civil": {"en": "Civil works", "fr": "Génie civil"},
    "f.civil.hint": {
        "en": "Foundations, plant room or container, fencing, access, earthing.",
        "fr": "Fondations, local technique ou conteneur, clôture, accès, mise à la terre."},
    "f.development": {"en": "Development", "fr": "Frais de développement"},
    "f.development.hint": {
        "en": "Feasibility, survey, permits, design and the developer's own time before "
              "financial close. Spent once and never replaced.",
        "fr": "Faisabilité, levés, autorisations, études et temps du développeur avant "
              "le bouclage financier. Dépensés une fois, jamais remplacés."},
    "f.collection": {"en": "Energy billed and collected",
                     "fr": "Énergie facturée et encaissée"},
    "f.collection.hint": {
        "en": "Share of the energy served that is actually paid for. One means every "
              "kilowatt-hour delivered is billed and collected, which no rural mini-grid "
              "achieves.",
        "fr": "Part de l'énergie servie qui est réellement payée. Un signifie que chaque "
              "kilowattheure distribué est facturé et encaissé, ce qu'aucun mini-réseau "
              "rural n'atteint."},

    "group.project": {"en": "The project", "fr": "Le projet"},
    "group.currency": {"en": "Display currency", "fr": "Monnaie d'affichage"},
    "group.grid": {"en": "National grid", "fr": "Réseau national"},
    "group.equipment": {"en": "Prices and equipment", "fr": "Prix et matériel"},
    "group.advanced": {"en": "Architecture and control", "fr": "Architecture et conduite"},

    # ---------------------------------------------------------------- form fields
    "f.trajectory": {"en": "Demand growth", "fr": "Croissance de la demande"},
    "f.trajectory.hint": {
        "en": "How fast consumption grows with the age of the connection.",
        "fr": "Rythme auquel la consommation croît avec l'ancienneté du raccordement."},
    "f.maturity": {"en": "Age of the connection", "fr": "Ancienneté du raccordement"},
    "f.maturity.hint": {
        "en": "Zero for a new site; twelve for a grid in service for a year.",
        "fr": "Zéro pour un site neuf ; douze pour un réseau en service depuis un an."},
    "f.horizon": {"en": "Project horizon", "fr": "Horizon du projet"},
    "f.discount": {"en": "Discount rate", "fr": "Taux d'actualisation"},
    "f.diesel": {"en": "Diesel price", "fr": "Prix du gazole"},
    "f.tariff": {"en": "Target tariff", "fr": "Tarif visé"},
    "f.tariff.hint": {
        "en": "Levelised-cost target; the tool reports the subsidy that reaches it.",
        "fr": "Cible de coût actualisé ; l'outil rapporte la subvention qui l'atteint."},
    "f.growth": {"en": "Annual demand growth", "fr": "Croissance annuelle de la demande"},
    "f.growth.hint": {
        "en": "Used by the financial appraisal alone, to project revenue. The sizing is done "
              "for the year and age stated; serving that growth is what the expansion plan "
              "is for.",
        "fr": "Employée par l'analyse financière seule, pour projeter les recettes. Le "
              "dimensionnement porte sur l'année et l'ancienneté déclarées ; servir cette "
              "croissance est l'objet du plan d'extension."},
    "f.currency": {"en": "Local currency", "fr": "Monnaie locale"},
    "f.currency.hint": {
        "en": "Amounts are shown in this currency; the computation stays in dollars.",
        "fr": "Les montants sont affichés dans cette monnaie ; le calcul reste en dollars."},
    "f.per_eur": {"en": "Local units per euro", "fr": "Unités locales par euro"},
    "f.per_eur.hint": {
        "en": "Fixed parity for the CFA franc; market rate for the others.",
        "fr": "Parité fixe pour le franc CFA ; taux de marché pour les autres."},
    "f.usd_eur": {"en": "Dollars per euro", "fr": "Dollars par euro"},
    "f.grid.connected": {"en": "Connected to the grid", "fr": "Raccordement au réseau"},
    "f.grid.connected.hint": {
        "en": "An intermittent grid displaces the battery, not the fuel: it is the generating "
              "set that grows, storage no longer having to carry every night alone.",
        "fr": "Un réseau intermittent déplace la batterie, pas le gazole : c'est le groupe "
              "qui grossit, le stockage n'ayant plus à porter seul chaque nuit."},
    "f.grid.availability": {"en": "Grid availability", "fr": "Disponibilité du réseau"},
    "f.grid.availability.hint": {
        "en": "Share of hours the feeder is energised.",
        "fr": "Part des heures où le départ est sous tension."},
    "f.grid.outage": {"en": "Typical outage length", "fr": "Durée typique d'une coupure"},
    "f.grid.outage.hint": {
        "en": "What the plant must carry alone, and therefore what sizes the storage. An "
              "availability figure does not say it.",
        "fr": "Ce que la centrale doit porter seule, et donc ce qui dimensionne le stockage. "
              "Une moyenne de disponibilité ne le dit pas."},
    "f.grid.import": {"en": "Imported energy price", "fr": "Prix de l'énergie importée"},
    "f.grid.import.hint": {
        "en": "To be taken from the utility: a regulated tariff is country-specific and often "
              "banded. The value offered is an order of magnitude and nothing more.",
        "fr": "À relever auprès du distributeur : un tarif réglementé est propre au pays et "
              "souvent par tranches. La valeur proposée n'est qu'un ordre de grandeur."},
    "f.grid.export": {"en": "Exported energy price", "fr": "Prix de l'énergie exportée"},
    "f.grid.export.hint": {
        "en": "Zero when injection is not paid for; the surplus is then curtailed.",
        "fr": "Zéro si l'injection n'est pas rémunérée ; le surplus est alors écrêté."},
    "f.grid.capacity": {"en": "Connection capacity", "fr": "Puissance de raccordement"},
    "f.grid.capacity.hint": {
        "en": "Zero to impose no limit beyond the converter's own.",
        "fr": "Zéro pour n'imposer aucune limite au-delà de celle de la conversion."},
    "f.grid.cost": {"en": "Connection cost", "fr": "Coût du raccordement"},
    "f.grid.cost.hint": {"en": "Line, metering, protection.",
                         "fr": "Ligne, comptage, protections."},
    "f.grid.uncertain": {"en": "Treat the arrival as uncertain",
                         "fr": "Traiter l'arrivée comme incertaine"},
    "f.grid.uncertain.hint": {
        "en": "For a village where the line is announced without a date. The expansion plan "
              "then branches on its arrival: what is committed today must stand whether it "
              "comes or not. Moot where the grid is already there, or plainly is not coming.",
        "fr": "Pour un village où la ligne est annoncée sans date. Le plan d'extension "
              "branche alors sur son arrivée : ce qu'on engage aujourd'hui doit tenir qu'elle "
              "vienne ou non. Sans objet quand le réseau est déjà là, ou manifestement pas "
              "prévu."},
    "f.pv_cost": {"en": "Photovoltaic", "fr": "Photovoltaïque"},
    "f.batt_cost": {"en": "Storage", "fr": "Stockage"},
    "f.inv_cost": {"en": "Power electronics", "fr": "Électronique de puissance"},
    "f.string_cost": {"en": "String inverters", "fr": "Onduleurs de chaîne"},
    "f.pv_life": {"en": "Photovoltaic service life", "fr": "Durée de vie du photovoltaïque"},
    "f.batt_life": {"en": "Storage service life", "fr": "Durée de vie du stockage"},
    "f.inv_life": {"en": "Conversion service life", "fr": "Durée de vie de la conversion"},
    "f.coupling": {"en": "Coupling", "fr": "Couplage"},
    "f.coupling.hint": {
        "en": "The divided array holds the two pure arrangements as its corners.",
        "fr": "Le champ divisé contient les deux dispositions pures comme cas extrêmes."},
    "f.ratio_dc": {"en": "Array admitted per kW, battery bus",
                   "fr": "Champ admis par kW, bus batterie"},
    "f.ratio_ac": {"en": "Array admitted per kW, load bus",
                   "fr": "Champ admis par kW, bus charge"},
    "f.reserve": {"en": "Look-ahead reserve", "fr": "Réserve d'anticipation"},
    "f.reserve.hint": {
        "en": "Multiplies the energy the controller keeps for the night ahead.",
        "fr": "Multiplie l'énergie que l'automate garde pour la nuit à venir."},
    "f.lookahead": {"en": "Look-ahead window", "fr": "Fenêtre d'anticipation"},
    "f.setpoint": {"en": "Generator setpoint", "fr": "Consigne du groupe"},
    "f.voll": {"en": "Unserved energy", "fr": "Énergie non distribuée"},
    "f.service": {"en": "Service level required", "fr": "Taux de service exigé"},
    "f.service.hint": {
        "en": "Least share of demand a sizing must serve to be retained. Leave at zero to "
              "require nothing and let the price of unserved energy arbitrate alone; raise it "
              "to 0.98 when a concession imposes one.",
        "fr": "Part minimale de la demande qu'un dimensionnement doit servir pour être "
              "retenu. Laissez à zéro pour ne rien exiger et laisser le coût de l'énergie non "
              "distribuée arbitrer seul ; portez-le à 0,98 quand une concession l'impose."},
    "f.solver": {"en": "Solver", "fr": "Solveur"},
    "arch.0": {"en": "Average consumption, spread through the day",
               "fr": "Consommation moyenne, étalée sur la journée"},
    "arch.1": {"en": "Frugal, strictly evening", "fr": "Sobre, strictement vespéral"},
    "arch.2": {"en": "Heavy consumer", "fr": "Gros consommateur"},
    "arch.3": {"en": "Steady, low peak", "fr": "Régulier, faible pointe"},

    # The dispatch chart. Its legend names the three ways a kilowatt reaches the load,
    # in the order the controller tries them.
    "chart.months.alt": {"en": "Energy served per month, by origin",
                         "fr": "Énergie servie par mois, par origine"},
    "state.site_saved": {"en": "Community “{name}” saved.",
                         "fr": "Communauté « {name} » enregistrée."},
    "state.failed": {"en": "Failed.", "fr": "Échec."},
    "chart.week.alt": {"en": "Power served hour by hour over the busiest week",
                       "fr": "Puissance servie heure par heure sur la semaine la plus sollicitée"},
    "chart.pv_load": {"en": "Photovoltaic to load", "fr": "Photovoltaïque vers la charge"},
    "chart.discharge": {"en": "Storage discharge", "fr": "Décharge du stockage"},
    "chart.generator": {"en": "Generator", "fr": "Groupe électrogène"},
    "chart.demand": {"en": "Demand", "fr": "Demande"},
    "chart.soc": {"en": "State of charge (right axis, kWh)",
                  "fr": "État de charge (échelle de droite, kWh)"},

    # The appraisal, including the cases where a figure does not exist: a project whose
    # revenue never covers its capital has no rate of return and no payback year, and
    # saying so plainly is better than printing a zero.
    "fin.at_tariff": {"en": "at a tariff of {tariff}", "fr": "au tarif de {tariff}"},
    "fin.disc_never": {"en": "discounted: never", "fr": "actualisé : jamais"},
    "fin.disc": {"en": "discounted: {n} years", "fr": "actualisé : {n} ans"},
    "fin.of_which": {"en": "of which {n} subsidised", "fr": "dont {n} subventionnés"},
}


def t(key: str, lang: str = DEFAULT) -> str:
    """One string, in the language asked for, falling back to English."""
    entry = STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(lang) or entry.get(DEFAULT, key)


def has(key: str) -> bool:
    """Whether the catalogue carries this string at all."""
    return key in STRINGS


def catalogue(lang: str = DEFAULT) -> dict[str, str]:
    """Every string in one language, for the page to hold."""
    return {key: t(key, lang) for key in STRINGS}
