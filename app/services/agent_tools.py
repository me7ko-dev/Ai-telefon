"""Описание на 4-те инструмента за ElevenLabs – на едно място.

От тук се генерират и конфигурацията за API-то (автоматична синхронизация),
и таблиците за ръчна настройка в панела.
"""

from dataclasses import dataclass, field

DATE_DESC = "Датата във формат ГГГГ-ММ-ДД, напр. 2026-10-08. Изчисли я от днешната дата."
TIME_DESC = "Началният час във формат ЧЧ:ММ, напр. 10:30."
PHONE_DESC = "Телефонният номер на клиента, само цифри, напр. 0888123456."


@dataclass
class Param:
    name: str
    description: str
    required: bool = True
    dynamic_variable: str | None = None  # стойността идва от ElevenLabs, не от модела


@dataclass
class ToolSpec:
    name: str
    description: str
    params: list[Param] = field(default_factory=list)


def tool_specs(cancel_only_own_number: bool = False) -> list[ToolSpec]:
    cancel_params = [
        Param("phone", "Телефонът, на който е записан часът, само цифри."),
        Param("date", DATE_DESC),
        Param("time", "Часът на записа (ЧЧ:ММ) – само ако инструментът е върнал, че има няколко записа в деня.", required=False),
    ]
    if cancel_only_own_number:
        cancel_params.append(
            Param("caller_id", "Номерът, от който се обажда клиентът.", required=False, dynamic_variable="system__caller_id")
        )
    return [
        ToolSpec(
            "check_availability",
            "Проверява свободните часове за дадена услуга в даден ден. Извикай го, преди да предложиш час на клиента. "
            "Ако денят е зает или почивен, връща най-близкия ден със свободни часове.",
            [
                Param("service", "Услугата, която иска клиентът, както я е казал, напр. „мъжко подстригване“."),
                Param("date", DATE_DESC),
            ],
        ),
        ToolSpec(
            "book_appointment",
            "Записва час. Извикай го САМО след като си повторил всички данни и клиентът е потвърдил с „да“. "
            "Ако часът е зает, връща алтернативи.",
            [
                Param("name", "Името на клиента."),
                Param("phone", PHONE_DESC),
                Param("service", "Услугата, напр. „мъжко подстригване“."),
                Param("date", DATE_DESC),
                Param("time", TIME_DESC),
            ],
        ),
        ToolSpec(
            "cancel_appointment",
            "Отменя записан час по телефон и дата. Извикай го след като клиентът е потвърдил, че иска отмяна.",
            cancel_params,
        ),
        ToolSpec(
            "take_message",
            "Записва съобщение за собственика – когато не знаеш отговора, клиентът иска да говори с човек "
            "или има нестандартна молба.",
            [
                Param("name", "Името на клиента."),
                Param("phone", PHONE_DESC),
                Param("message", "Съобщението накратко, с всички важни подробности."),
            ],
        ),
    ]


def elevenlabs_tool_config(spec: ToolSpec, tools_url: str, secret_id: str) -> dict:
    """tool_config за POST/PATCH /v1/convai/tools (тип webhook)."""
    properties = {}
    for p in spec.params:
        prop = {"type": "string"}
        if p.dynamic_variable:
            prop["dynamic_variable"] = p.dynamic_variable
        else:
            prop["description"] = p.description
        properties[p.name] = prop
    return {
        "type": "webhook",
        "name": spec.name,
        "description": spec.description,
        "response_timeout_secs": 20,
        # Грешките (напр. липсващо поле) да стигат до агента, за да може да се поправи.
        "tool_error_handling_mode": "passthrough",
        "api_schema": {
            "url": f"{tools_url}/{spec.name}",
            "method": "POST",
            "content_type": "application/json",
            "request_headers": {"X-Tool-Secret": {"secret_id": secret_id}},
            "request_body_schema": {
                "type": "object",
                "description": f"Параметри за {spec.name}",
                "required": [p.name for p in spec.params if p.required],
                "properties": properties,
            },
        },
    }
