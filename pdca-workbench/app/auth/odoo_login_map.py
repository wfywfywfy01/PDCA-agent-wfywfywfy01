# -*- coding: utf-8 -*-
"""Odoo 经销商 login → 已有 PDCA username。

来源：桌面《用户 (res.users).xlsx》（公司=经销商，33 条）。
免登按 Odoo `res.users.login` 找本地号；对不上会新建孤儿号，所以能唯一对上门店的才进这张表。

总部（VMG / reStore）和无 PDCA 门店的账号不映射。
"""
from __future__ import annotations

# Odoo login -> PDCA users.username（须已存在且绑了 dealer_id）
ODOO_LOGIN_TO_USERNAME: dict[str, str] = {
    "Altyn Zaman": "AltynZamanH.J.",
    "gaoya@gmail.com": "BINBININVESTMENT(CAMBODIA)COLTD",
    "afshinbehzadi111@gmail.com": "BehzadiBoutique",
    "vr@bestcom.net.ua": "Bestcom",
    "Billionaire Collections": "BillionaireCollections",
    "Bizcon Group": "BizconGroup",
    "CLICK TECH SERVICES": "CLICKTECHSERVICES",
    "Dar Al Sabaek": "DarAlSabaek",
    "GURU ELECTRONICS": "GURUELECTRONICSSINGAPOREPTELTD",
    "jainchatters@gmail.com": "SiddSenthil",
    "anatolii.shyrokov@gmail.com": "IQ-QUESTSP.ZO.O.",
    "TC Azimut": "LLCTCAzimut",
    "Luxem": "LuxemStore",
    "My Shops": "MyShopsElectronicsTradingLLC",
    "ac.aviapark.msk@re-store.ru": "RSTR_MSK_АВИАПАРК",
    "ac.atrium.msk@re-store.ru": "RSTR_MSK_АТРИУМ",
    "ac.afimoll.msk@re-store.ru": "RSTR_MSK_АФИМОЛЛ_СИТИ",
    "ac.neglinnaya.msk@re-store.ru": "RSTR_MSK_НЕГЛИННАЯ_8",
    "ac.rigamoll.msk@re-store.ru": "RSTR_MSK_РИГА_МОЛЛ",
    "Robo Trading": "RoboTradingLtd",
    "Safiranhamrah": "SafiranHamrah",
    "wasim@suninternationalgt.com": "SunInternationalGeneralTrading",
    "VERTU LONDON LTD": "VERTULONDONLTD",
    "Veysel Sevis": "VeyselSevisLtd",
    "VST ECS": "siam_paragon",
}

# Excel 里有、但不能对上唯一门店：免登拒绝，禁止新建孤儿号。
ODOO_LOGIN_REFUSE_CREATE: frozenset[str] = frozenset(
    {
        "ara_avetisyan@gmail.com",
        "thakerjaydxb@gmail.com",
        "Veehoo Ukraine",
        "yawboakye@gmail.com",
        "Yuemmai",
        "Sun International General Trading-PT",
        "VMG Communication",
        "reStore",
    }
)


def resolve_pdca_username(odoo_login: str) -> str:
    """把 Odoo login 收成 PDCA username；无映射则原样返回。

    @param odoo_login Odoo `res.users.login`
    @returns 已有 PDCA username，或原 login
    """
    login = (odoo_login or "").strip()
    if not login:
        return ""
    return ODOO_LOGIN_TO_USERNAME.get(login) or login


def should_refuse_odoo_sso_create(odoo_login: str) -> bool:
    """未映射经销商：禁止 ensure_vps_user 新建号。"""
    login = (odoo_login or "").strip()
    return login in ODOO_LOGIN_REFUSE_CREATE
