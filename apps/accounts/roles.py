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
AD_GROUP_TO_ROLE = {
    # "CN=Portal-Operators,OU=Groups,DC=company,DC=local": ROLE_OPERATOR,
}
