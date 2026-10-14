"""
Роли портала. Реализуются как группы Django: пользователь попадает в группу —
получает права роли. На проде группы будут наполняться из AD (маппинг на этапе 9).

Имена ролей держим в одном месте, чтобы не хардкодить строки по коду.
"""

ROLE_OPERATOR = "Оператор"
ROLE_DOWNTIME_SPECIALIST = "Специалист по простоям"
ROLE_IT_MANAGER = "Руководитель ИТ"
ROLE_MANAGEMENT = "Руководство предприятия"
ROLE_ADMIN = "Администратор"

# Полный список ролей — используется при создании групп.
ALL_ROLES = [
    ROLE_OPERATOR,
    ROLE_DOWNTIME_SPECIALIST,
    ROLE_IT_MANAGER,
    ROLE_MANAGEMENT,
    ROLE_ADMIN,
]

# Заготовка для будущего маппинга групп AD -> роли портала (этап 9).
# Ключ — имя группы в AD, значение — роль портала.
# Точные имена групп ищет и подтверждает ИТ-служба (question.md, В25).
AD_GROUP_TO_ROLE = {
    # "CN=Portal-Operators,OU=Groups,DC=company,DC=local": ROLE_OPERATOR,
    # "CN=Portal-Downtime,OU=Groups,DC=company,DC=local": ROLE_DOWNTIME_SPECIALIST,
    # "CN=Portal-IT-Managers,OU=Groups,DC=company,DC=local": ROLE_IT_MANAGER,
    # "CN=Portal-Management,OU=Groups,DC=company,DC=local": ROLE_MANAGEMENT,
    # "CN=Portal-Admins,OU=Groups,DC=company,DC=local": ROLE_ADMIN,
}


def roles_for_ad_groups(ad_groups) -> list[str]:
    """
    Превращает список групп AD в список ролей портала по карте AD_GROUP_TO_ROLE.

    Простыми словами: пришёл сотрудник из AD с набором групп — смотрим, каким
    ролям портала они соответствуют. Незнакомые группы просто игнорируем.
    """
    roles: list[str] = []
    for group in ad_groups or []:
        role = AD_GROUP_TO_ROLE.get(group)
        if role and role not in roles:
            roles.append(role)
    return roles
