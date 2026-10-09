LV_NAMES = {
    "RU": "Krievija", "BY": "Baltkrievija", "US": "ASV", "GB": "Lielbritānija", "DE": "Vācija", "FR": "Francija",
    "CN": "Ķīna", "PL": "Polija", "LT": "Lietuva", "LV": "Latvija", "EE": "Igaunija", "FI": "Somija", "SE": "Zviedrija",
    "NO": "Norvēģija", "DK": "Dānija", "UA": "Ukraina", "IT": "Itālija", "CA": "Kanāda", "JP": "Japāna", "TR": "Turcija",
    "IR": "Irāna", "KZ": "Kazahstāna", "NL": "Nīderlande", "CZ": "Čehija", "SK": "Slovākija", "HU": "Ungārija",
    "AT": "Austrija", "CH": "Šveice", "BE": "Beļģija", "ES": "Spānija", "PT": "Portugāle", "GR": "Grieķija",
    "IE": "Īrija", "IS": "Islande", "LU": "Luksemburga", "RO": "Rumānija", "BG": "Bulgārija", "HR": "Horvātija",
    "SI": "Slovēnija", "RS": "Serbija", "MD": "Moldova", "GE": "Gruzija", "AM": "Armēnija", "AZ": "Azerbaidžāna",
    "UZ": "Uzbekistāna", "IN": "Indija", "IL": "Izraēla", "KR": "Dienvidkoreja", "KP": "Ziemeļkoreja",
    "AU": "Austrālija", "BR": "Brazīlija", "AR": "Argentīna", "MX": "Meksika", "EG": "Ēģipte", "SA": "Saūda Arābija",
    "AE": "AAE", "VA": "Svētais Krēsls", "SMOM": "Maltas ordenis", "MK": "Ziemeļmaķedonija", "AL": "Albānija",
    "ME": "Melnkalne", "BA": "Bosnija un Hercegovina", "CY": "Kipra", "MT": "Malta", "VN": "Vjetnama", "TH": "Taizeme",
    "ID": "Indonēzija", "PK": "Pakistāna", "ZA": "Dienvidāfrika", "NG": "Nigērija", "CU": "Kuba", "SY": "Sīrija",
    "IQ": "Irāka", "QA": "Katara", "KW": "Kuveita", "TM": "Turkmenistāna", "TJ": "Tadžikistāna", "KG": "Kirgizstāna",
    "MN": "Mongolija", "CL": "Čīle", "CO": "Kolumbija", "PE": "Peru", "NZ": "Jaunzēlande", "MA": "Maroka", "DZ": "Alžīrija",
}


def lv_name(code, fallback):
    base = code.split("#")[0]
    if base.endswith("_CG"):
        n = LV_NAMES.get(base[:-3])
        return f"{n} (ģenerālkonsulāts)" if n else fallback
    return LV_NAMES.get(base, fallback)
