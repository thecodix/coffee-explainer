# Vendored from thecodix/roasters observatorio/scrapers/product_kind.py (same rules as the observatory).
# Used only when an export predates product_kind; newer exports carry the observatory's own label.
"""Tipo de producto y peso de la bolsa, compartidos por platform_spider.py e infra/db/reparse_products.py.

Decidido el 2026-10-05 (docs/panel-next-steps.md, tarea 4): tres tipos de café (single_origin, blend, coffee) y
cinco que no lo son (equipment, capsules, other_drink, merch, other). Los análisis de precio, origen y
representación usan solo café. Las palabras salen de los productos reales que el clasificador anterior dejaba en
«other» (captura del 2026-10-05, 26 537 filas de 314 tostadores), en los idiomas del panel.

Orden de las reglas, primero sobre el título y, si no dice nada, sobre el tipo y las etiquetas (la primera que casa
gana): 1. single origin explícito («Cup of Excellence»); 2. cápsulas; 3. equipo por palabra genérica («Moulin à
café») o un lote con marca de equipo y «+» («Lelit Bianca + 1 kg de café»); 4. vales, cursos, suscripciones, packs y comida; 5. bebidas que nunca son café (té, cascara, siropes); 6. café
con evidencia fuerte (palabra de café, mezcla, origen o variedad, más grano o un peso de bolsa) aunque nombre una
marca de equipo («Chemex blend 250 g»); 7. merch va antes del café fuerte; 8. marcas de equipo; 9. otras bebidas; 10. café por origen,
mezcla o variedad (en el título, una palabra de café sola no basta: «Coffee Latte servies»); 11. sin ninguna pista:
café si hay peso de bolsa, si no other.
"""

from __future__ import annotations

import html
import re

COFFEE_KINDS = {"single_origin", "blend", "coffee"}
KINDS = ("single_origin", "blend", "coffee", "equipment", "capsules", "other_drink", "merch", "other")

MIN_BAG_GRAMS = 50  # por debajo casi nunca es una bolsa: «2 gr» son dos grupos de una máquina
DESCRIPTION_BAG_RANGE = (100, 2500)  # en la descripción solo cuentan tamaños de bolsa habituales


def _words(*patterns: str) -> re.Pattern:
    """Palabras o prefijos (\\b al inicio; al final solo si el patrón acaba en $)."""
    parts = [p[:-1] + r"\b" if p.endswith("$") else p for p in patterns]
    return re.compile(r"\b(?:" + "|".join(parts) + ")", re.IGNORECASE)


_CAPSULES = _words("caps?ul", "c[áa]psul", "kapsel", "kapsul", "капсул", "κάψουλ", "nespresso", "dolce gusto",
                   "pods?$", "k-cups?$", "dosettes?$", "drip ?bags?$", "drips bags?$", "drip coffee bags?$")
_OTHER = _words(
    # vales regalo
    "gift ?cards?$", "gift ?vouchers?$", "vouchers?$", "gutschein", "geschenkkarte", "tarjeta regalo", "cheque[- ]cadeau",
    "carte[- ]cadeau", "buono regalo", "presentkort", "gavekort", "lahjakortti", "karta podarunkowa", "dárkov",
    "poukaz", "cartão presente", "vale regalo",
    # cursos
    "courses?$", "kurs", "curso", "cours$", "formation", "corso", "workshops?$", "masterclass", "curs$", "kursus", "koulutus",
    # suscripciones
    "subscriptions?$", "abo$", "abonnement", "suscripci", "abbonamento", "prenumeration", "předplatné", "prenumerata",
    "assinatura", "tilaus",
    # packs, cajas y lotes (el precio no es de una bolsa)
    "bundles?$", "tasting box", "gift box", "geschenkbox", "sampler", "discovery box", "coffee box", "caja regalo",
    "coffret", "zestaw", "sada$", "\\d+\\s*x\\s*\\d+\\s*g", "packs?$", "probier", "proefpakket", "sample set",
    "advent", "calendars?$", "calendario", "calendrier", "kalender", "\\d+[- ]months?$", "monthly", "mensual",
    "monatlich", "\\d+ monate", "\\d+ mois", "\\d+ mes(?:es)?$", "\\d+ kk$", "degustac", "degustacij",
    # otros que no son producto, y comida
    "shipping", "versand", "envío", "deposit", "pfand", "donation", "sablé", "biscuit", "cookies?$", "galleta",
    "keks", "pralin", "bonbon", "sugar", "azúcar", "zucker", "cukier", "cukr", "cukraus", "sucre$", "sladkor",
    "mascobado", "muscovado",
    "napój", "roślinn", "plant milk", "oat ?milk", "haferdrink", "bebida vegetal", "kaurajuoma",
)
_BEANS = _words(
    "whole ?beans?$", "beans?$", "bohnen", "grano", "grain$", "en grains?$", "zrn", "ziarn", "bönor", "bønner",
    "kahvipapu", "papu$", "boabe", "szemes", "pupel", "pupos", "oad$", "κόκκ", "moulu", "gemahlen", "molido",
    "mletá", "mielona", "jauhettu", "malet$", "malt$", "ground coffee",
    # compuestos, donde «bohnen» no empieza palabra
    "kaffeebohnen", "espressobohnen", "kaffebønner", "kaffebönor", "kaffibaunir", "koffiebonen", "kahvipavut",
)
_EQUIPMENT = _words(  # genéricos: ganan a «café» en el nombre («Moulin à café»)
    "grinders?$", "molinill", "moulin", "mühle", "kvarn", "kvern", "kaffekvarn", "mlýn", "młyn", "mlinac", "râșniț",
    "drippers?$", "brewers?$", "french press", "cafeter", "cafetière", "moka", "espresso machine", "espressomaskin",
    "kaffemaskin", "kaffemaschine", "espressomaschine", "machine espresso", "machine expresso", "espressokvern",
    "kaffekvern", "espressokvarn", "siebträger", "ekspres", "kávovar", "kahvinkeitin", "aparat$",
    "machine à café", "macchina", "kettles?$", "hervidor", "bouilloire", "wasserkocher", "vannkoker", "vattenkokare",
    "czajnik", "konvice", "scales?$", "báscula", "waage", "vekt$", "våg$", "waga$", "paper filters?$", "filtros de papel",
    "filtres$", "filtry$", "filtrai", "filteri$", "filtru$", "filtri$", "þjapp", "filterpapier", "papierfilter", "suodatinpaper", "mugs?$", "cups?$", "taza",
    "tasse", "kopp$", "kubek", "kubki", "hrn[eí]", "šálek", "tumbler", "thermos", "termo", "termiczn", "servers?$",
    "carafe", "jarra", "pitcher", "milk jug", "tamper", "portafilter", "knock ?box", "descal", "entkalk", "cleaning",
    "reinigung", "limpieza", "glass(?:es)?$", "glas$", "spare part", "ersatzteil", "gasket", "dichtung", "baskets?$",
    "scoops?$", "clips?$", "κούπα", "κουπα", "φλιτζ", "vekt", "coffee tools?$", "brita$", "water filter",
    "espressor", "screens?$", "puck", "diffuser", "puhast", "cleaner", "reiniger", "nettoyant", "limpiador",
    "masin", "filter ?papers?$", "grupper", "gruppi", "bottles?$", "butelk", "láhev", "botella", "flasche",
    "gourde", "wrench", "shaker", "silicone", "servies", "conservation", "canisters?$", "airscape", "storage",
    "funnel", "knock", "keyring", "nøkkelring", "nyckelring", "schlüsselanh", "t-särk", "bryggevekt", "kaffevekt",
    "veefilter", "messgerät", "melkkan", "coffee gear",
)
_EQUIPMENT_BRANDS = _words(  # marcas: un café con mezcla, grano o peso gana («Chemex blend 250 g»)
    "hario", "kinto", "fellow", "timemore", "comandante", "baratza", "eureka", "mahlk[öo]nig", "rancilio",
    "la marzocco", "lelit", "sage$", "breville", "jura$", "de'?longhi", "bialetti", "wilfa", "moccamaster",
    "technivorm", "acaia", "ceado", "mazzer", "victoria arduino", "synesso", "vbm$", "aeropress", "chemex", "kalita",
    "origami", "bonavita", "bodum", "1zpresso", "gaggia", "profitec", "bezzera", "keepcup", "huskee", "stagg",
    "brewista", "cafelat", "pullman", "motta", "puqpress", "cafiza", "urnex", "varia$", "niche zero", "df64", "dalla corte", "nucleus",
    "rocket espresso", "ecm$", "barista hustle", "loveramics", "notneutral", "cafec", "orea$", "april brewer",
    "faema",
)
_OTHER_DRINK = _words(
    "teas?$", "té$", "thé", "grüner tee", "schwarzer tee", "weißer tee", "früchtetee", "čaj", "herbat", "chá$", "tè$", "чай", "τσάι", "matcha", "chai$",
    "rooibos", "infusi", "tisane", "kräutertee", "chocolat", "chocolate", "schokolade", "šokolad", "czekolad",
    "čokolád", "cioccolat", "kakao", "cacao", "cocoa", "syrups?$", "sirop", "sirope", "sirup", "syrop", "sīrup",
    "monin$", "kombucha", "juice", "lemonade", "cascara", "ronnefeldt", "síróp", "torani",
)
# Bebidas que nunca son café aunque el nombre diga «café» («Cascara - kahvimarja»): se miran antes que el café.
_SURELY_DRINK = _words("cascara", "teas?$", "english breakfast", "earl grey", "tb$", "grønn te", "grön te",
                       "svart te", "green tea", "black tea", "maté$", "genmaicha", "sencha", "gyokuro", "oolong",
                       "hojicha", "spritz", "soda$", "cans?$", "thé", "čaj", "herbat", "matcha", "chai$", "rooibos", "syrups?$",
                       "sirop", "sirope", "sirup", "syrop", "síróp", "monin$", "torani", "ronnefeldt", "kombucha")
_MERCH = _words(
    "t-?shirts?$", "tee-shirt", "tees?$", "hoodie", "sweatshirt", "sudadera", "camiseta", "gorra", "beanie", "caps?$",
    "hats?$", "tote", "stickers?$", "posters?$", "aprons?$", "delantal", "schürze", "tablier", "förkläde",
    "fartuch", "books?$", "libro", "livre", "buch$", "bok$", "książk", "socks?$", "calcetines", "socken",
    "keychain", "llavero", "merch", "info cards?$", "postcards?$",
)
_BLEND = _words(
    "blends?$", "mezcla", "mélange", "mischung", "miscela", "blanding", "blandning", "směs", "zmes", "mieszank",
    "keverék", "amestec", "sekoitus", "segaj", "mix$", "house espresso", "χαρμάνι", "χαρμανι", "смесь", "суміш",
)
_SINGLE = _words("single origin", "single-origin", "single estate", "origen único", "monorigin", "mono origin",
                 "monoorigine", "jednorodn", "single farm", "micro ?lot", "microlote", "cup of excellence", "coe$")
# Variedades y procesos que solo usa el café de especialidad: cuentan como palabra de café.
_COFFEE_TERMS = _words("gesha", "geisha", "pacamara", "bourbon", "caturra", "typica", "sl ?28", "sl ?34", "catua[ií]",
                       "castillo", "heirloom", "74110", "74158", "sidra", "wush ?wush", "maragog", "anaerob",
                       "carbonic", "washed", "lavado", "black honey", "red honey", "yellow honey", "honey process")
_COFFEE = _words(
    "coffee", "caf[eé]$", "caffè", "caffe$", "kaffe", "kaffee", "kahvi", "kohv", "kafija", "kava$", "kavos", "kawa",
    "káva", "kávé", "cafea", "kafe$", "kafa$", "kafu$", "kaffi", "καφ[εέ]", "кофе", "кава", "кафа", "espresso",
    "decaf", "descafeinado", "entkoffeiniert", "filter roast", "filterkaffee", "omni roast", "espressorost",
)
# Nombres de los países de origen en los idiomas del panel (además de los de platform_spider.ORIGIN_COUNTRY_ISO).
ORIGIN_NAMES = {
    "kolumbien": "CO", "kolumbia": "CO", "kolumbie": "CO", "kolumbija": "CO", "columbia": "CO", "colombie": "CO",
    "colômbia": "CO", "κολομβία": "CO", "колумбия": "CO", "колумбія": "CO",
    "äthiopien": "ET", "ethiopie": "ET", "éthiopie": "ET", "etiopie": "ET", "etiópia": "ET", "etiopija": "ET",
    "αιθιοπία": "ET", "эфиопия": "ET", "ефіопія": "ET", "etiyopya": "ET",
    "brasilien": "BR", "brazylia": "BR", "brazílie": "BR", "brazília": "BR", "brazilija": "BR", "brazilia": "BR",
    "brésil": "BR", "brasile": "BR", "brasilia": "BR", "βραζιλία": "BR", "бразилия": "BR", "бразилія": "BR",
    "keňa": "KE", "kenija": "KE", "kénya": "KE", "κένυα": "KE", "кения": "KE", "кенія": "KE",
    "ruanda": "RW", "ruandas": "RW", "rwandas": "RW", "guatemalas": "GT", "gwatemala": "GT", "hondurasas": "HN",
    "perou": "PE", "pérou": "PE", "peruu": "PE", "salwador": "SV", "salvadoras": "SV", "nikaragua": "NI",
    "kostaryka": "CR", "kostarika": "CR", "kosta rika": "CR", "indonesien": "ID", "indonezja": "ID",
    "indonésie": "ID", "jemen": "YE", "yémen": "YE", "burundis": "BI", "tansania": "TZ", "tanzanie": "TZ",
    "mexiko": "MX", "meksyk": "MX", "mexique": "MX", "panama": "PA", "panamá": "PA",
    "bazilja": "BR", "brazilië": "BR", "colombië": "CO", "ethiopië": "ET", "brasilië": "BR",
}

# Copied from observatorio/scrapers/platform_spider.py.
ORIGIN_COUNTRY_ISO = {
    "colombia": "CO", "brasil": "BR", "brazil": "BR",
    "etiopía": "ET", "etiopia": "ET", "ethiopia": "ET",
    "perú": "PE", "peru": "PE", "honduras": "HN", "nicaragua": "NI",
    "guatemala": "GT", "kenia": "KE", "kenya": "KE", "ruanda": "RW",
    "rwanda": "RW", "costa rica": "CR", "panamá": "PA", "panama": "PA",
    "el salvador": "SV", "méxico": "MX", "mexico": "MX",
    "indonesia": "ID", "vietnam": "VN", "india": "IN", "uganda": "UG",
    "yemen": "YE", "bolivia": "BO", "ecuador": "EC",
    "república dominicana": "DO", "dominican republic": "DO",
    "burundi": "BI", "tanzania": "TZ",
    "papúa nueva guinea": "PG", "papua new guinea": "PG",
    "filipinas": "PH", "philippines": "PH", "malawi": "MW",
    "zambia": "ZM", "camerún": "CM", "cameroon": "CM",
    "puerto rico": "PR", "china": "CN", "laos": "LA", "myanmar": "MM",
    "tailandia": "TH", "thailand": "TH",
}

# Después, los nombres en los idiomas del panel («Kolumbien», «Éthiopie»), que load_parsed.py también resuelve.

_REGION_KEYWORDS = [
    # Colombia
    "Huila", "Nariño", "Cauca", "Tolima", "Antioquia", "Santander",
    "Sierra Nevada de Santa Marta", "Sierra Nevada", "Quindío", "Risaralda",
    "Caldas", "Eje Cafetero",
    # Guatemala
    "Antigua", "Acatenango", "Atitlán", "Cobán", "Verapaz", "Fraijanes",
    "Huehuetenango", "San Marcos",
    # Honduras
    "Copán", "Opalaca", "Montecillos", "Comayagua", "El Paraíso", "Agalta",
    "Marcala",
    # Etiopía
    "Yirgacheffe", "Yirga Chefe", "Sidama", "Sidamo", "Guji", "Harrar",
    "Harar", "Limu", "Limmu", "Jimma", "Lekempti", "Wollega", "Kaffa",
    "Bonga",
    # Brasil
    "Cerrado Mineiro", "Sul de Minas", "Mantiqueira de Minas",
    "Serra da Mantiqueira", "Mogiana", "Alta Mogiana", "Matas de Minas",
    "Caparaó", "Montanhas do Espírito Santo", "Norte de Minas",
    "Chapada de Minas",
    # Tanzania
    "Kilimanjaro", "Arusha", "Ruvuma", "Mbinga", "Songwe", "Mbozi", "Kagera",
    # Uganda
    "Mount Elgon", "Bugisu", "Rwenzori", "West Nile", "Masaka",
    # Nicaragua
    "Jinotega", "Matagalpa", "Nueva Segovia", "Segovia",
    # Perú
    "Cajamarca", "Amazonas", "San Martín", "Piura", "Chanchamayo",
    "Satipo", "Cuzco", "Cusco", "La Convención", "Quillabamba", "Sandia",
    "Huánuco", "Ayacucho",
    # Ecuador
    "Loja", "Zamora Chinchipe", "Manabí", "Jipijapa", "El Oro", "Los Ríos",
    "Guayas",
]




def _origin_in(text: str) -> bool:
    """Un país de origen o una región cafetera conocida («Yirgacheffe», «Huila») en el texto."""
    low = text.lower()
    # Prefijo, no palabra entera: «Ethiopian», «Kenyan», «Colombian».
    return any(re.search(rf"\b{re.escape(name.lower())}", low)
               for name in (*ORIGIN_COUNTRY_ISO, *ORIGIN_NAMES, *_REGION_KEYWORDS))


def _grams_from_variant_title(title: str):
    """Copied from observatorio/scrapers/platform_spider.py: '250g', '250 gr', '1kg' -> grams, else None."""
    if not title:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|grs?|g)\b", title, re.IGNORECASE)
    if not m:
        return None
    qty = float(m.group(1).replace(",", "."))
    unit = m.group(2).lower()
    return int(qty * 1000) if unit == "kg" else int(qty)


def grams(text: str | None) -> int | None:
    """'250g', '250 g', '250gr', '1kg', '0,5 kg' → gramos; None si no hay o es menor que MIN_BAG_GRAMS."""
    value = _grams_from_variant_title(text or "")
    return value if value and value >= MIN_BAG_GRAMS else None


def classify(title: str, product_type: str | None = None, tags: list[str] | tuple = (),
             extras: list[str] | tuple = ()) -> str:
    """Uno de KINDS. Decide el título; el tipo y las etiquetas solo si el título no dice nada (una etiqueta «V60» o
    «subscription» no convierte en equipo o suscripción un «Etiopia Aricha»). `extras`: títulos de variantes u
    opciones, que aportan el peso de la bolsa."""
    weight = bool(grams(title) or any(grams(e) for e in extras))
    kind = _classify_text(title or "", weight, strict=True)
    if kind is None:
        kind = _classify_text(" ".join(filter(None, [product_type or "", *tags])), weight)
    if kind is None:
        kind = "coffee" if weight else "other"
    return kind


def _classify_text(text: str, weight: bool, strict: bool = False) -> str | None:
    """El tipo que indica `text`, o None si no hay ninguna pista. Ver el orden en el docstring del módulo."""
    if not text.strip():
        return None
    if _SINGLE.search(text):  # antes que «cup»: «Cup of Excellence» es café
        return "single_origin"
    if _CAPSULES.search(text):
        return "capsules"
    if _EQUIPMENT.search(text):  # antes que los packs: «BRITA pack», «filter papers (100 pack)»
        return "equipment"
    if "+" in text and _EQUIPMENT_BRANDS.search(text):  # «Lelit Bianca + formation + 1 kg de café»: un lote de equipo
        return "equipment"
    if _OTHER.search(text):
        return "other"
    if _SURELY_DRINK.search(text):
        return "other_drink"
    if _MERCH.search(text):  # «The Coffee Roaster's Companion book» no es café aunque tenga peso
        return "merch"
    coffee_kind = _coffee_kind(text)
    if coffee_kind and (_BEANS.search(text) or weight):
        return coffee_kind
    if _EQUIPMENT_BRANDS.search(text):
        return "equipment"
    if _OTHER_DRINK.search(text):
        return "other_drink"
    if strict and coffee_kind == "coffee" and not _COFFEE_TERMS.search(text):
        return None  # «Coffee Latte servies»: una palabra de café sola en el título no basta; deciden tipo y etiquetas
    return coffee_kind


def _coffee_kind(text: str) -> str | None:
    if _BLEND.search(text):
        return "blend"
    if _SINGLE.search(text) or _origin_in(text):
        return "single_origin"
    if _COFFEE.search(text) or _BEANS.search(text) or _COFFEE_TERMS.search(text):
        return "coffee"
    return None


def is_coffee(kind: str | None) -> bool:
    return kind in COFFEE_KINDS


_WEIGHT_IN_TEXT = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|grs?|g)\b", re.IGNORECASE)


def bag_grams(first_variant: str | None, title: str | None, description: str | None, *, coffee: bool) -> int | None:
    """Peso de la bolsa del precio capturado (el de la primera variante): su título, si no el del producto y, solo
    para café, un único tamaño de bolsa en la descripción (las recetas, «18 g in», quedan fuera de rango)."""
    for text in (first_variant, title):
        value = grams(text)
        if value:
            return value
    if not coffee or not description:
        return None
    plain = re.sub(r"<[^>]+>", " ", html.unescape(description))
    sizes = set()
    for amount, unit in _WEIGHT_IN_TEXT.findall(plain):
        value = float(amount.replace(",", "."))
        value = int(value * 1000) if unit.lower() == "kg" else int(value)
        if DESCRIPTION_BAG_RANGE[0] <= value <= DESCRIPTION_BAG_RANGE[1]:
            sizes.add(value)
    return sizes.pop() if len(sizes) == 1 else None
