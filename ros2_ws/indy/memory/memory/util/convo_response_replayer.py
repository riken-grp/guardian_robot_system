import tkinter as tk
from tkinter import CHAR, END, messagebox, ttk
from tkinter.font import Font

from bson import ObjectId
from openai import OpenAI
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

# from openai.types.chat import ChatCompletion


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Search & Generate UI")

        font = Font(self.root, family="Helvetica", size=12)
        # em_font = Font(self.root, family="Helvetica", size=12, slant="italic")
        self.root.option_add("*Font", font)

        s = ttk.Style()
        s.theme_use("alt")

        # ---- Internal State ----
        self.selected_csv_path = None  # Path from the FILE picker
        self.dbclient: MongoClient | None = None
        self.dbcoll: Collection | None = None
        self.llm_client: OpenAI | None = None
        self.data = {}

        # ---- Validation (Temperature: float, Retries: int) ----
        vcmd_float = (self.root.register(self._validate_float), "%P")
        vcmd_int = (self.root.register(self._validate_int), "%P")

        # ---- Layout containers ----
        main = ttk.Frame(self.root, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Make two equal columns for SEARCH and GENERATE
        # main.columnconfigure(0, weight=1)
        # main.columnconfigure(1, weight=2)

        main.columnconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(2, weight=1)

        # =========================
        # MODEL SECTION
        # =========================
        llm_frame = ttk.LabelFrame(main, text="LLM", padding=(12, 0))
        llm_frame.grid(
            row=0,
            column=0,
            rowspan=2,
            padx=(0, 5),
            pady=(0, 5),
            sticky="nsew",
        )
        llm_frame.columnconfigure(0, weight=1)
        llm_frame.columnconfigure(1, weight=1)

        self.llm_frame = llm_frame

        for i in range(3):
            llm_frame.rowconfigure(i * 2 + 1, weight=1)

        # MODEL URL
        ttk.Label(llm_frame, text="URL").grid(
            row=0, column=0, pady=(5, 0), sticky="new"
        )
        self.model_url_var = tk.StringVar()
        model_url_entry = ttk.Entry(llm_frame, textvariable=self.model_url_var)
        model_url_entry.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 5),
            padx=(0, 0),
        )
        # API KEY
        ttk.Label(llm_frame, text="API KEY").grid(row=2, column=0, sticky="ew")
        self.model_apikey_var = tk.StringVar()
        model_apikey_entry = ttk.Entry(
            llm_frame, textvariable=self.model_apikey_var, show="*"
        )
        model_apikey_entry.grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 5),
            padx=(0, 0),
        )
        # MODEL NAME
        ttk.Label(llm_frame, text="MODEL NAME").grid(
            row=4, column=0, sticky="w"
        )
        self.model_name_var = tk.StringVar()
        model_name_entry = ttk.Entry(
            llm_frame, textvariable=self.model_name_var
        )
        model_name_entry.grid(
            row=5, column=0, sticky="nsew", pady=(0, 5), padx=(0, 5)
        )
        # DB CONNECT button
        llm_btn = ttk.Button(
            llm_frame, text="CONNECT", command=self.on_llm_connect_click
        )
        llm_btn.grid(row=5, column=1, pady=(0, 5), sticky="nsew")

        # =========================
        # DATABASE DATA
        # =========================
        database_frame = ttk.LabelFrame(main, text="MONGO DB", padding=(6, 5))
        database_frame.grid(
            row=0, column=1, padx=(0, 5), pady=(0, 5), sticky="new"
        )

        self.database_frame = database_frame

        database_frame.columnconfigure(0, weight=1)
        database_frame.columnconfigure(1, weight=1)
        database_frame.columnconfigure(2, weight=1)
        # for c in range(4):
        #     database_frame.columnconfigure(c, weight=1)

        # MONGO URI
        ttk.Label(database_frame, text="URI").grid(
            row=0, column=0, columnspan=3, sticky="w"
        )
        self.mongo_uri_var = tk.StringVar()
        mongo_uri_entry = ttk.Entry(
            database_frame, textvariable=self.mongo_uri_var
        )
        mongo_uri_entry.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(0, 5),
            padx=(0, 0),
        )

        # MONGO PORT
        ttk.Label(database_frame, text="PORT").grid(
            row=2, column=0, sticky="ew"
        )
        self.mongo_port_var = tk.StringVar()
        mongo_port_entry = ttk.Entry(
            database_frame,
            textvariable=self.mongo_port_var,
            validate="key",
            validatecommand=vcmd_int,
        )
        mongo_port_entry.grid(
            row=3, column=0, sticky="ew", pady=(0, 5), padx=(0, 5)
        )

        # MONGO COLLECTION
        ttk.Label(database_frame, text="COLLECTION").grid(
            row=2, column=1, sticky="ew"
        )
        self.mongo_coll_var = tk.StringVar()
        mongo_coll_entry = ttk.Entry(
            database_frame, textvariable=self.mongo_coll_var
        )
        mongo_coll_entry.grid(
            row=3, column=1, sticky="ew", pady=(0, 5), padx=(0, 5)
        )

        # DB CONNECT button
        dbconn_btn = ttk.Button(
            database_frame, text="CONNECT", command=self.on_connect_click
        )
        dbconn_btn.grid(row=3, column=2, rowspan=1, pady=(0, 5), sticky="nsew")

        # =========================
        # SEARCH SECTION
        # =========================
        search_frame = ttk.LabelFrame(main, text="SEARCH", padding=(6, 5))
        search_frame.grid(
            row=1, column=1, padx=(0, 5), pady=(0, 5), sticky="new"
        )

        # ID
        ttk.Label(search_frame, text="ID").grid(
            row=0, column=0, sticky="ew", padx=(0, 5)
        )
        self.id_var = tk.StringVar()
        id_entry = ttk.Entry(search_frame, textvariable=self.id_var)
        id_entry.grid(row=0, column=1, sticky="ew", padx=(0, 5))

        # LOAD button
        load_btn = ttk.Button(
            search_frame, text="LOAD as is", command=self.on_load_click
        )
        load_btn.grid(row=0, column=2, sticky="ew", ipadx=5.0)

        # search_frame.columnconfigure(0, weight=1)
        search_frame.columnconfigure(1, weight=1)

        # =========================
        # GENERATE SECTION
        # =========================
        gen_frame = ttk.LabelFrame(main, text="RE-GENERATION", padding=(6, 5))
        gen_frame.grid(
            row=2, column=0, pady=(0, 5), columnspan=2, sticky="nsew"
        )

        for c in range(4):
            gen_frame.columnconfigure(c, weight=2)

        # TODO add scrollbars

        # PERSONA (multiline)
        ttk.Label(gen_frame, text="PERSONA").grid(
            row=0, column=0, columnspan=2, sticky="new"
        )
        persona_frame = ttk.Frame(gen_frame)
        persona_frame.columnconfigure(0, weight=1)
        persona_frame.rowconfigure(0, weight=1)
        self.persona_txt = tk.Text(persona_frame, height=8, wrap=CHAR)
        self.persona_txt.grid(
            row=0,
            column=0,
            sticky="nsew",
            pady=(0, 5),
            padx=(0, 5),
        )
        persona_scrollbar = ttk.Scrollbar(
            persona_frame, orient=tk.VERTICAL, command=self.persona_txt.yview
        )
        self.persona_txt.configure(yscrollcommand=persona_scrollbar.set)
        self.persona_txt.configure(spacing1=6, spacing2=6, spacing3=6)
        persona_scrollbar.grid(row=0, column=1, sticky="nsew")
        persona_frame.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(0, 5),
            padx=(0, 5),
        )

        # PROMPT (multiline)
        ttk.Label(gen_frame, text="PROMPT").grid(
            row=0, column=2, columnspan=2, sticky="new"
        )
        prompt_frame = ttk.Frame(gen_frame)
        prompt_frame.columnconfigure(0, weight=1)
        prompt_frame.rowconfigure(0, weight=1)
        self.prompt_txt = tk.Text(prompt_frame, height=8, wrap=CHAR)
        self.prompt_txt.grid(
            row=0,
            column=0,
            sticky="nsew",
            pady=(0, 5),
            padx=(0, 5),
        )
        prompt_scrollbar = ttk.Scrollbar(
            prompt_frame, orient=tk.VERTICAL, command=self.prompt_txt.yview
        )
        self.prompt_txt.configure(yscrollcommand=prompt_scrollbar.set)
        self.prompt_txt.configure(spacing1=6, spacing2=6, spacing3=6)
        prompt_scrollbar.grid(row=0, column=1, sticky="nsew")
        prompt_frame.grid(
            row=1,
            column=2,
            columnspan=2,
            sticky="nsew",
            pady=(0, 5),
            padx=(0, 5),
        )

        # TODO
        # HISTORY (multiline, read-only to the user)
        # ttk.Label(gen_frame, text="HISTORY").grid(
        #     row=0, column=2, columnspan=2, sticky="new"
        # )

        # history_frame = ttk.Frame(gen_frame)
        # history_frame.columnconfigure(0, weight=1)
        # history_frame.rowconfigure(0, weight=1)

        # self.history_txt = tk.Text(history_frame, height=8, wrap=CHAR)
        # self.history_txt.grid(
        #     row=0,
        #     column=0,
        #     sticky="nsew",
        #     pady=(0, 5),
        #     padx=(0, 5),
        # )
        # history_scrollbar = ttk.Scrollbar(
        #     history_frame, orient=tk.VERTICAL, command=self.history_txt.yview
        # )
        # self.history_txt.configure(yscrollcommand=history_scrollbar.set)
        # self.history_txt.configure(spacing1=6, spacing2=6, spacing3=6)
        # history_scrollbar.grid(row=0, column=1, sticky="nsew")
        # history_frame.grid(
        #     row=1,
        #     column=2,
        #     columnspan=2,
        #     rowspan=3,
        #     sticky="nsew",
        #     pady=(0, 5),
        #     padx=(0, 5),
        # )
        # self.history_txt.tag_config("em", font=em_font)
        # self.history_txt.tag_config("rowalt", background="gray69")

        # self.history_txt.configure(state="disabled")

        # RECORDED RESPONSE
        ttk.Label(gen_frame, text="RECORDED RESPONSE").grid(
            row=2, column=0, columnspan=2, sticky="new"
        )
        self.rec_resp_txt = tk.Text(gen_frame, height=3, wrap=CHAR)
        self.rec_resp_txt.grid(
            row=3,
            column=0,
            columnspan=2,
            rowspan=1,
            sticky="nsew",
            padx=(0, 5),
            pady=(0, 5),
        )
        self.rec_resp_txt.configure(spacing1=6, spacing2=6, spacing3=6)
        self.rec_resp_txt.configure(state="disabled")

        # TEMPERATURE (float)
        tempt_frame = ttk.Frame(gen_frame)
        tempt_frame.columnconfigure(1, weight=1)

        ttk.Label(tempt_frame, text="TEMPERATURE").grid(
            row=0, column=0, sticky="ew", padx=(0, 0)
        )
        self.temperature_var = tk.StringVar()
        temp_entry = ttk.Entry(
            tempt_frame,
            textvariable=self.temperature_var,
            validate="key",
            validatecommand=vcmd_float,
        )
        temp_entry.grid(
            row=0, column=1, sticky="sew", pady=(0, 5), padx=(0, 5)
        )

        # GENERATE button
        gen_btn = ttk.Button(
            tempt_frame, text="GENERATE BELOW", command=self.on_generate_click
        )
        gen_btn.grid(
            row=0,
            column=2,
            rowspan=1,
            sticky="nsew",
            padx=(5, 0),
            pady=(0, 5),
        )

        tempt_frame.grid(
            row=2,
            column=2,
            columnspan=2,
            sticky="nsew",
            pady=(0, 5),
            padx=(0, 5),
        )

        self.gen_resp_txt = tk.Text(gen_frame, height=3, wrap=CHAR)
        self.gen_resp_txt.grid(
            row=3,
            column=2,
            columnspan=2,
            rowspan=1,
            sticky="nsew",
            pady=(0, 5),
        )
        self.gen_resp_txt.configure(spacing1=6, spacing2=6, spacing3=6)

        # Spacer to make text areas expand
        gen_frame.rowconfigure(1, weight=1)  # PERSONA
        gen_frame.rowconfigure(3, weight=1)  # PROMPT
        # gen_frame.rowconfigure(5, weight=1)  # HISTORY

        # Default Values
        self.mongo_uri_var.set("localhost")
        self.mongo_port_var.set("29110")
        self.mongo_coll_var.set("llm_log")

        self.model_url_var.set("http://localhost:28001/v1/")
        self.model_name_var.set("indy-instruct")

    # ---------- Validation helpers ----------
    def _validate_float(self, proposed: str) -> bool:
        """Allow empty (user typing) or a valid float representation."""
        if proposed.strip() == "":
            return True
        try:
            float(proposed)
            return True
        except ValueError:
            self.root.bell()
            return False

    def _validate_int(self, proposed: str) -> bool:
        """Allow empty (user typing) or a valid non-negative integer."""
        if proposed.strip() == "":
            return True
        if proposed.isdigit():
            return True
        self.root.bell()
        return False

    def set_read_only_text(
        self, widget: tk.Text, text: str, format_history=False
    ):
        was_disabled = str(widget.cget("state")) == "disabled"
        if was_disabled:
            widget.configure(state="normal")
        self.set_txtbox_text(widget, text)
        if format_history:
            # Highlight All Even Lines (rowalt)
            self.format_pattern(widget, r"^.+$", "rowalt", skip=1, regexp=True)
            # Italicize  All Starts (em)
            self.format_pattern(widget, r"^.+(?=「)", "em", regexp=True)
        if was_disabled:
            widget.configure(state="disabled")

    def set_txtbox_text(self, widget: tk.Text, text: str):
        widget.delete("1.0", END)
        widget.insert("1.0", text)

    # https://stackoverflow.com/questions/3781670/how-to-highlight-text-in-a-tkinter-text-widget
    def format_pattern(
        self,
        widget: tk.Text,
        pattern: str,
        tag: str,
        skip: int = 0,
        regexp: bool = False,
    ):
        start = widget.index("1.0")
        end = widget.index("end")

        widget.mark_set("matchStart", start)
        widget.mark_set("matchEnd", start)
        widget.mark_set("searchLimit", end)

        count = tk.IntVar()
        idx = 0

        while True:
            index = widget.search(
                pattern,
                index="matchEnd",
                stopindex="searchLimit",
                count=count,
                regexp=regexp,
            )

            if not index or not count.get():
                break

            widget.mark_set("matchStart", index)
            widget.mark_set("matchEnd", f"{index} + {count.get()} chars")

            if idx == skip:
                widget.tag_add(tag, "matchStart", "matchEnd")
                idx = 0
            else:
                idx += 1

    def enable_labelframe(self, widget: ttk.LabelFrame):
        for child in widget.winfo_children():
            child.configure(state="enable")  # type: ignore

    def disable_labelframe(self, widget: ttk.LabelFrame):
        for child in widget.winfo_children():
            child.configure(state="disable")  # type: ignore

    def on_connect_click(self):
        db_uri = self.mongo_uri_var.get()
        db_port = int(self.mongo_port_var.get())
        db_coll = self.mongo_coll_var.get()

        try:
            self.dbclient = MongoClient(db_uri, db_port)
            if "memory_settings" not in self.dbclient.list_database_names():
                raise PyMongoError("'memory_settings' not found in Database")
            if (
                db_coll
                not in self.dbclient["memory_settings"].list_collection_names()
            ):
                raise PyMongoError(
                    "Collection not found in Client's 'memory_settings'."
                )
            self.dbcoll = self.dbclient["memory_settings"][db_coll]
        except PyMongoError as e:
            messagebox.showerror("Database Error", str(e))
            self.enable_labelframe(self.database_frame)
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self.enable_labelframe(self.database_frame)
        else:
            self.disable_labelframe(self.database_frame)

    def on_llm_connect_click(self):
        # Load LLM info into OpenAI object
        base_url = self.model_url_var.get()
        api_key = self.model_apikey_var.get()
        self.llm_client = OpenAI(
            base_url=base_url,
            api_key=api_key if api_key else "EMPTY",
        )

        try:
            print(self.llm_client.base_url)
            print(", ".join(str(m.id) for m in self.llm_client.models.list()))
        except Exception as e:
            messagebox.showerror("Error", repr(e))
            self.enable_labelframe(self.llm_frame)
        else:
            self.disable_labelframe(self.llm_frame)

    # ---------- Button handlers ----------

    def load_data(self):
        _id = self.id_var.get()
        if self.dbcoll is None:
            messagebox.showerror("Error", "No Collection/Connection.")
            return

        self.data = self.dbcoll.find_one(
            {"_id": ObjectId(_id), "msgs": {"$exists": True, "$size": 2}}
        )

        if self.data is None:
            messagebox.showerror(
                "Error", "No suitable Data found for that OID."
            )
            self.data = {}
            return

        msgs = self.data["msgs"]
        persona = msgs[0]["content"].strip()
        prompt = msgs[1]["content"].strip()
        # history = "\n".join(
        #     ("ユーザー" if "user" in rec["role"] else "ロボット")
        #     + f"「{rec['content'].strip()}」"
        #     for rec in msgs[2:]
        # )
        rec_resp = self.data["completion"]["choices"][0]["message"][
            "content"
        ].strip()

        self.set_txtbox_text(self.persona_txt, persona)
        self.set_txtbox_text(self.prompt_txt, prompt)
        # self.set_read_only_text(self.history_txt, history, format_history=True)
        self.set_read_only_text(self.rec_resp_txt, rec_resp)

        self.temperature_var.set(str(float(self.data["opts"]["temperature"])))

    def on_load_click(self):
        self.load_data()

    def on_generate_click(self):
        if self.data is None or self.llm_client is None:
            return

        msgs = []

        # Add Persona
        msgs.append(
            {"role": "system", "content": self.persona_txt.get("1.0", "end")}
        )
        # Add Prompt
        msgs.append(
            {"role": "system", "content": self.prompt_txt.get("1.0", "end")}
        )
        # Get Temperature
        temp = float(self.temperature_var.get())

        # Call Model

        resp = self.llm_client.chat.completions.create(
            model=self.data["completion"]["model"],
            messages=msgs,
            # stop=self.data["opts"]["stop"],
            temperature=temp,
        )

        if resp and resp.choices and resp.choices[0].message.content:
            self.set_txtbox_text(
                self.gen_resp_txt, resp.choices[0].message.content
            )
        else:
            messagebox.showerror(
                "Generation Error", "No Data Received from LLM."
            )

    # ---------- App loop ----------
    def run(self):
        self.root.minsize(900, 600)
        self.root.mainloop()


if __name__ == "__main__":
    root = tk.Tk()
    # Optional: use ttk theme for nicer look (platform dependent)
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass
    app = App(root)
    app.run()
