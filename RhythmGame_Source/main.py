from ui_manager import AppUI, MainMenu, apply_theme

def main():
    apply_theme()
    app = AppUI()
    app.show_screen(MainMenu)
    app.mainloop()

if __name__ == "__main__":
    main()
