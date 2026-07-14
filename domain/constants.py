# -*- coding: utf-8 -*-
"""Domain constants for RMKO."""
NEXT_STEPS = [
    "Связаться по счету", "Напомнить об оплате", "Уточнить решение по счету",
    "Отправить КП", "Обновить счет", "Согласовать договор", "Подтвердить оплату",
    "Уточнить наличие товара", "Предложить аналог", "Сообщить о поступлении товара",
    "Согласовать доставку", "Напомнить о заборе товара", "Уточнить причину отказа",
]
REJECT_REASONS = ["высокая цена", "выбрали другого поставщика", "клиент передумал",
                  "нет обратной связи от клиента", "не выделили средства",
                  "не оплатили", "нет новых РН", "другое"]
DELETE_REASONS = ["счет создан ошибочно", "замена счета", "пересоздан документ",
                  "дубль", "другое"]
CHECK_STATUSES = ["Новая", "Отработано", "Закрыто автоматически"]
GOODS_CHECK = ["Ожидает проверки", "Проверено"]

# поля, которые редактирует менеджер (разрешены в PATCH)
EDITABLE = {
    "last_contact", "close_date",
    "reject_reason", "delete_reason", "notes", "in_stock",
    "closing_docs", "delivery", "contract_num", "lead_source", "mgr_comment",
}

# SQL Condition Strings extracted from core.py
SQL_IS_CLOSED = "computed_status IN ('Выдан', 'Удален', 'Удалён') OR deleted=1"
SQL_OVERDUE = """
    CASE WHEN plan_contact IS NOT NULL AND plan_contact != '' 
    THEN date(substr(plan_contact, 7, 4) || '-' || substr(plan_contact, 4, 2) || '-' || substr(plan_contact, 1, 2)) < date('now', 'localtime')
    ELSE 0 END
"""
SQL_LEVEL = """
    CASE 
      WHEN status_1c = 'Ошибка' THEN 'error'
      WHEN computed_status = 'Выдан' THEN 'done'
      WHEN computed_status IN ('Удален', 'Удалён') OR deleted=1 THEN 'done'
      WHEN plan_contact IS NOT NULL AND plan_contact != '' AND date(substr(plan_contact, 7, 4) || '-' || substr(plan_contact, 4, 2) || '-' || substr(plan_contact, 1, 2)) < date('now', 'localtime') THEN 'risk'
      ELSE 'ready'
    END
"""
