(function () {
    "use strict";

    function refreshIcons() {
        if (window.lucide) window.lucide.createIcons({ attrs: { "aria-hidden": "true" } });
    }

    refreshIcons();

    function enhanceSearchableSelect(select, index) {
        if (select.dataset.searchableReady === "true") return;
        select.dataset.searchableReady = "true";

        const choices = Array.from(select.options)
            .filter((option) => option.value)
            .map((option) => ({ value: option.value, label: option.textContent.trim() }));
        const placeholder = select.dataset.placeholder || "Type to search and choose";
        const selected = choices.find((choice) => choice.value === select.value);
        const wasRequired = select.required;
        const wrapper = document.createElement("div");
        const input = document.createElement("input");
        const menu = document.createElement("div");
        const inputId = `${select.id || "search-select"}-search-${index}`;
        const menuId = `${inputId}-options`;
        let visibleChoices = choices;
        let activeIndex = -1;

        wrapper.className = "search-select";
        input.className = "form-control search-select-input";
        input.id = inputId;
        input.type = "text";
        input.value = selected ? selected.label : "";
        input.placeholder = placeholder;
        input.autocomplete = "off";
        input.required = wasRequired;
        input.setAttribute("role", "combobox");
        input.setAttribute("aria-autocomplete", "list");
        input.setAttribute("aria-expanded", "false");
        input.setAttribute("aria-controls", menuId);
        menu.className = "search-select-menu";
        menu.id = menuId;
        menu.setAttribute("role", "listbox");
        menu.hidden = true;

        const fieldGroup = select.closest(".form-group");
        const label = fieldGroup ? fieldGroup.querySelector(`label[for="${select.id}"]`) : null;
        if (label) label.setAttribute("for", inputId);

        select.required = false;
        select.tabIndex = -1;
        select.setAttribute("aria-hidden", "true");
        select.classList.add("search-select-native");
        select.parentNode.insertBefore(wrapper, select);
        wrapper.append(input, menu, select);

        function closeMenu() {
            menu.hidden = true;
            activeIndex = -1;
            input.setAttribute("aria-expanded", "false");
            input.removeAttribute("aria-activedescendant");
        }

        function choose(choice) {
            select.value = choice.value;
            input.value = choice.label;
            input.setCustomValidity("");
            select.dispatchEvent(new Event("change", { bubbles: true }));
            closeMenu();
        }

        function setActive(nextIndex) {
            const items = Array.from(menu.querySelectorAll("[role='option']"));
            items.forEach((item) => item.classList.remove("active"));
            if (!items.length) {
                activeIndex = -1;
                return;
            }
            activeIndex = Math.max(0, Math.min(nextIndex, items.length - 1));
            items[activeIndex].classList.add("active");
            input.setAttribute("aria-activedescendant", items[activeIndex].id);
            items[activeIndex].scrollIntoView({ block: "nearest" });
        }

        function renderMenu(query = "") {
            const normalized = query.trim().toLowerCase();
            visibleChoices = choices.filter((choice) => choice.label.toLowerCase().includes(normalized)).slice(0, 50);
            menu.replaceChildren();
            activeIndex = -1;

            if (!visibleChoices.length) {
                const empty = document.createElement("div");
                empty.className = "search-select-empty";
                empty.textContent = "No matching option";
                menu.appendChild(empty);
            } else {
                visibleChoices.forEach((choice, choiceIndex) => {
                    const option = document.createElement("button");
                    option.type = "button";
                    option.id = `${menuId}-${choiceIndex}`;
                    option.className = "search-select-option";
                    option.setAttribute("role", "option");
                    option.setAttribute("aria-selected", choice.value === select.value ? "true" : "false");
                    option.textContent = choice.label;
                    option.addEventListener("mousedown", (event) => {
                        event.preventDefault();
                        choose(choice);
                    });
                    menu.appendChild(option);
                });
            }
            menu.hidden = false;
            input.setAttribute("aria-expanded", "true");
        }

        input.addEventListener("focus", () => {
            input.select();
            renderMenu("");
        });
        input.addEventListener("input", () => {
            const exact = choices.find((choice) => choice.label.toLowerCase() === input.value.trim().toLowerCase());
            select.value = exact ? exact.value : "";
            input.setCustomValidity("");
            renderMenu(input.value);
        });
        input.addEventListener("keydown", (event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                if (menu.hidden) renderMenu(input.value);
                if (activeIndex < 0) setActive(event.key === "ArrowDown" ? 0 : visibleChoices.length - 1);
                else setActive(activeIndex + (event.key === "ArrowDown" ? 1 : -1));
            } else if (event.key === "Enter" && !menu.hidden && activeIndex >= 0) {
                event.preventDefault();
                choose(visibleChoices[activeIndex]);
            } else if (event.key === "Escape") {
                closeMenu();
            }
        });
        input.addEventListener("blur", () => {
            window.setTimeout(() => {
                if (select.value) {
                    const current = choices.find((choice) => choice.value === select.value);
                    input.value = current ? current.label : "";
                } else {
                    const matches = choices.filter((choice) => choice.label.toLowerCase().includes(input.value.trim().toLowerCase()));
                    if (input.value.trim() && matches.length === 1) choose(matches[0]);
                    else input.value = "";
                }
                closeMenu();
            }, 100);
        });

        const form = select.closest("form");
        if (form && wasRequired) {
            form.addEventListener("submit", (event) => {
                if (!select.value) {
                    event.preventDefault();
                    input.setCustomValidity("Choose an option from the list.");
                    input.reportValidity();
                    input.focus();
                    renderMenu(input.value);
                }
            });
        }
    }

    document.querySelectorAll("select[data-searchable-select='true']").forEach(enhanceSearchableSelect);

    const sidebar = document.getElementById("portal-sidebar");
    const sidebarToggles = document.querySelectorAll("[data-sidebar-toggle]");
    function setSidebarOpen(open) {
        if (!sidebar) return;
        sidebar.classList.toggle("open", open);
        document.body.classList.toggle("no-scroll", open);
        sidebarToggles.forEach((button) => button.setAttribute("aria-expanded", String(open)));
    }
    sidebarToggles.forEach((button) => {
        button.setAttribute("aria-expanded", "false");
        button.addEventListener("click", () => setSidebarOpen(!sidebar.classList.contains("open")));
    });
    if (sidebar) sidebar.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => setSidebarOpen(false)));

    const publicMenu = document.querySelector("[data-public-nav]");
    const publicMenuButton = document.querySelector("[data-public-menu]");
    if (publicMenu && publicMenuButton) {
        const setPublicMenuOpen = (open) => {
            publicMenu.classList.toggle("open", open);
            publicMenuButton.setAttribute("aria-expanded", String(open));
        };
        publicMenuButton.setAttribute("aria-expanded", "false");
        publicMenuButton.addEventListener("click", () => setPublicMenuOpen(!publicMenu.classList.contains("open")));
        publicMenu.querySelectorAll("a").forEach((link) => link.addEventListener("click", () => setPublicMenuOpen(false)));
    }

    document.querySelectorAll("[data-tabs]").forEach((tabsRoot) => {
        const buttons = tabsRoot.querySelectorAll("[data-tab]");
        const items = tabsRoot.querySelectorAll("[data-tab-item]");
        const select = (name) => {
            buttons.forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
            items.forEach((item) => { item.hidden = item.dataset.tabItem !== name; });
        };
        buttons.forEach((button) => button.addEventListener("click", () => select(button.dataset.tab)));
        if (buttons.length) select(buttons[0].dataset.tab);
    });

    document.querySelectorAll("[data-modal-open]").forEach((button) => {
        button.addEventListener("click", () => {
            const modal = document.getElementById(button.dataset.modalOpen);
            if (!modal) return;
            modal.classList.add("open");
            modal.setAttribute("aria-hidden", "false");
            document.body.classList.add("no-scroll");
            const focusTarget = modal.querySelector("input, select, textarea, button");
            if (focusTarget) setTimeout(() => focusTarget.focus(), 50);
        });
    });

    document.querySelectorAll("[data-modal-close]").forEach((button) => {
        button.addEventListener("click", () => {
            const modal = button.closest(".modal");
            if (!modal) return;
            modal.classList.remove("open");
            modal.setAttribute("aria-hidden", "true");
            document.body.classList.remove("no-scroll");
        });
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            setSidebarOpen(false);
            if (publicMenu && publicMenuButton) {
                publicMenu.classList.remove("open");
                publicMenuButton.setAttribute("aria-expanded", "false");
            }
            document.querySelectorAll(".modal.open").forEach((modal) => {
                modal.classList.remove("open");
                modal.setAttribute("aria-hidden", "true");
            });
            document.body.classList.remove("no-scroll");
        }
    });

    window.addEventListener("resize", () => {
        if (window.innerWidth > 980) setSidebarOpen(false);
        if (window.innerWidth > 980 && publicMenu && publicMenuButton) {
            publicMenu.classList.remove("open");
            publicMenuButton.setAttribute("aria-expanded", "false");
        }
    });

    document.querySelectorAll("[data-accordion] article button").forEach((button) => {
        button.addEventListener("click", () => button.closest("article").classList.toggle("open"));
    });

    document.querySelectorAll(".password-toggle").forEach((button) => {
        button.addEventListener("click", () => {
            const input = button.parentElement.querySelector("input");
            if (!input) return;
            input.type = input.type === "password" ? "text" : "password";
            button.innerHTML = `<i data-lucide="${input.type === "password" ? "eye" : "eye-off"}"></i>`;
            refreshIcons();
        });
    });

    const voiceButton = document.querySelector("[data-voice-button]");
    if (voiceButton) {
        voiceButton.addEventListener("click", () => {
            voiceButton.classList.toggle("voice-recording");
            voiceButton.title = voiceButton.classList.contains("voice-recording") ? "Recording — tap to stop" : "Record a voice message";
        });
    }

    document.querySelectorAll(".filter-pills").forEach((group) => {
        group.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
            group.querySelectorAll("button").forEach((item) => item.classList.remove("active"));
            button.classList.add("active");
        }));
    });

    document.querySelectorAll("[data-table-search]").forEach((input) => {
        const target = document.getElementById(input.dataset.tableSearch);
        if (!target) return;
        input.addEventListener("input", () => {
            const query = input.value.trim().toLowerCase();
            target.querySelectorAll("[data-search-row]").forEach((row) => {
                row.hidden = Boolean(query) && !row.textContent.toLowerCase().includes(query);
            });
        });
    });

    document.querySelectorAll("[data-focus-search]").forEach((link) => {
        link.addEventListener("click", () => {
            const input = document.getElementById(link.dataset.focusSearch);
            if (input) setTimeout(() => input.focus(), 150);
        });
    });

    const messageList = document.getElementById("message-list");
    if (messageList) messageList.scrollTop = messageList.scrollHeight;

    document.querySelectorAll(".toast-message").forEach((toast) => {
        setTimeout(() => toast.remove(), 6500);
    });
})();
