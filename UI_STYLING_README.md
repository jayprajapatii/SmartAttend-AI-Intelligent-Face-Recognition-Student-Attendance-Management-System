# SmartAttend AI UI Styling Update

The UI has been refreshed with a centralized design system for a cleaner and more consistent desktop application.

## Main changes
- Shared adaptive light/dark color palette in `ui/design_system.py`
- Modernized application shell and page background
- Wider, cleaner RBAC-aware sidebar with active navigation state
- Consistent primary, secondary and danger button styles
- Modernized login and splash screens
- Adaptive muted text colors instead of fixed gray text
- Consistent card borders and corner radius
- Improved Treeview/table styling
- Existing database, authentication, face recognition and attendance logic preserved

## Environment
This safe source package intentionally does not contain the original `.env` file. Copy your existing `.env` into the project root, or create it from `.env.example`.

## Run
1. Restore/copy your project `.env` file.
2. Install the existing project dependencies.
3. Start the project with your normal `main.py` command.
