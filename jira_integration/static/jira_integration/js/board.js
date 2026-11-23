(() => {
    const root = document.getElementById("jira-board");
    if (!root) return;

    const message = document.getElementById("board-message");
    const login = document.getElementById("board-login");
    const retry = document.getElementById("board-retry");
    const sprint = document.getElementById("board-sprint");
    const updated = document.getElementById("board-updated");
    const columns = document.getElementById("board-columns");

    function makeElement(tag, text, className) {
        const element = document.createElement(tag);
        element.textContent = text;
        if (className) element.className = className;
        return element;
    }

    function makeCard(issue) {
        const card = document.createElement("article");
        card.className = "jira-task-card";

                const link = document.createElement("a");
        link.textContent = issue.key;
        link.href = root.dataset.issueUrlTemplate.replace(
            "ISSUEKEY",
            encodeURIComponent(issue.key)
        );
        card.appendChild(link);
        card.appendChild(makeElement("h3", issue.summary));
        card.appendChild(makeElement("p", issue.status));

        const assignee = issue.assignee?.display_name || "Не назначен";
        card.appendChild(makeElement("p", `Исполнитель: ${assignee}`));

        return card;
    }

    function renderBoard(data) {
        if (!data.sprint) {
            message.textContent = "Нет доступных задач в активном спринте.";
            return;
        }

        sprint.textContent = data.sprint.name;

        if (data.synced_at) {
            const date = new Date(data.synced_at);
            if (!Number.isNaN(date.getTime())) {
                updated.textContent =
                    `Данные обновлены: ${date.toLocaleString("ru-RU")}`;
            }
        }

        let total = 0;
        const fragment = document.createDocumentFragment();

        for (const column of data.columns) {
            const section = document.createElement("section");
            section.className = "jira-board-column";
            section.appendChild(makeElement("h3", column.status));

            for (const issue of column.issues) {
                section.appendChild(makeCard(issue));
                total += 1;
            }

            fragment.appendChild(section);
        }

        columns.replaceChildren(fragment);
        message.textContent = total
            ? `Задач на доске: ${total}`
            : "В этом спринте нет доступных задач.";
    }

    async function loadBoard() {
        retry.hidden = true;
        retry.disabled = true;
        login.hidden = true;
        message.textContent = "Загружаем задачи…";
        sprint.textContent = "";
        updated.textContent = "";
        columns.replaceChildren();
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
                message.textContent = "У вас нет доступа к доске практиканта.";
                return;
            }

            if (!response.ok) {
                throw new Error("Не удалось загрузить доску.");
            }

            renderBoard(await response.json());
        } catch {
            columns.replaceChildren();
            sprint.textContent = "";
            updated.textContent = "";
            message.textContent =
                "Не удалось загрузить задачи. Попробуйте ещё раз.";
            retry.hidden = false;
        } finally {
            retry.disabled = false;
            root.setAttribute("aria-busy", "false");
        }
    }

    retry.addEventListener("click", loadBoard);
    loadBoard();
})();