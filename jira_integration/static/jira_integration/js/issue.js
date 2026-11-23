(() => {
    const root = document.getElementById("jira-issue");
    if (!root) return;

    const message = document.getElementById("issue-message");
    const login = document.getElementById("issue-login");
    const retry = document.getElementById("issue-retry");
    const content = document.getElementById("issue-content");
    const details = document.getElementById("issue-details");
    const fields = document.getElementById("issue-fields");
    const links = document.getElementById("issue-links");

    function addDetail(container, label, value) {
        const term = document.createElement("dt");
        term.textContent = label;

        const description = document.createElement("dd");
        description.textContent = value ?? "Не указано";

        container.append(term, description);
    }

    function formatDate(value) {
        if (!value) return "Нет данных";
        const date = new Date(value);
        return Number.isNaN(date.getTime())
            ? "Нет данных"
            : date.toLocaleString("ru-RU");
    }

    function renderIssue(issue) {
        document.getElementById("issue-key").textContent = issue.key;
        document.getElementById("issue-summary").textContent = issue.summary;

        details.replaceChildren();
        addDetail(details, "Проект", issue.project_key);
        addDetail(details, "Статус", issue.status.name);
        addDetail(details, "Тип", issue.issue_type);
        addDetail(details, "Приоритет", issue.priority);
        addDetail(
            details,
            "Исполнитель",
            issue.assignee?.display_name || "Не назначен"
        );
        addDetail(details, "Спринт", issue.sprint?.name || "Без спринта");
        addDetail(details, "Метки", issue.labels.join(", ") || "Нет");
        addDetail(details, "Обновлено в Jira", formatDate(issue.updated_at));
        addDetail(details, "Данные загружены", formatDate(issue.synced_at));

        fields.replaceChildren();
        const entries = Object.entries(issue.custom_fields);
        for (const [name, value] of entries) {
            const text = typeof value === "object" && value !== null
                ? JSON.stringify(value)
                : value;
            addDetail(fields, name, text);
        }
        document.getElementById("issue-fields-empty").hidden =
            entries.length > 0;

        links.replaceChildren();
        for (const relation of issue.links) {
            const item = document.createElement("li");
            const link = document.createElement("a");
            link.textContent = relation.target_key;
            link.href = root.dataset.issueUrlTemplate.replace(
                "ISSUEKEY",
                encodeURIComponent(relation.target_key)
            );

            const direction = relation.direction === "inward"
                ? "входящая"
                : "исходящая";

            item.append(
                link,
                document.createTextNode(
                    ` — ${relation.link_type}, ${direction} связь`
                )
            );
            links.appendChild(item);
        }
        document.getElementById("issue-links-empty").hidden =
            issue.links.length > 0;
    }

    async function loadIssue() {
        content.hidden = true;
        login.hidden = true;
        retry.hidden = true;
        retry.disabled = true;
        message.textContent = "Загружаем задачу…";
        root.setAttribute("aria-busy", "true");

        try {
            const response = await fetch(root.dataset.apiUrl, {
                credentials: "same-origin",
                headers: { Accept: "application/json" },
                cache: "no-store",
            });

            if (response.status === 401) {
                message.textContent = "Сессия закончилась. Войдите снова.";
                login.hidden = false;
                return;
            }

            if (response.status === 403) {
                message.textContent = "У вас нет доступа к этому разделу.";
                return;
            }

            if (response.status === 404) {
                message.textContent = "Задача не найдена или больше недоступна.";
                return;
            }

            if (!response.ok) {
                throw new Error("Не удалось загрузить задачу.");
            }

            renderIssue(await response.json());
            message.textContent = "";
            content.hidden = false;
        } catch {
            content.hidden = true;
            message.textContent =
                "Не удалось загрузить задачу. Попробуйте ещё раз.";
            retry.hidden = false;
        } finally {
            retry.disabled = false;
            root.setAttribute("aria-busy", "false");
        }
    }

    retry.addEventListener("click", loadIssue);
    loadIssue();
})();