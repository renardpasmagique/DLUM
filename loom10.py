import tkinter as tk
from tkinter import messagebox
import serial
import serial.tools.list_ports

class ServoSequencer:
    def __init__(self, root):
        self.root = root
        self.root.title("Séquenceur Servos 4×20")
        self.root.geometry("700x900")
        
        self.serial_conn = None
        self.current_line = 0
        
        # Grille 4 colonnes × 20 lignes (état: 0=blanc/baissé, 1=noir/levé)
        self.grid_state = [[0 for _ in range(4)] for _ in range(20)]
        self.cell_buttons = []
        
        self.create_widgets()
    
    def create_widgets(self):
        # === Connexion ===
        conn_frame = tk.LabelFrame(self.root, text="Connexion Arduino", padx=10, pady=10)
        conn_frame.pack(padx=10, pady=10, fill="x")
        
        tk.Label(conn_frame, text="Port:").grid(row=0, column=0)
        self.port_var = tk.StringVar()
        self.port_menu = tk.OptionMenu(conn_frame, self.port_var, "")
        self.port_menu.grid(row=0, column=1, padx=5)
        self.refresh_ports()
        
        tk.Button(conn_frame, text="Rafraîchir", command=self.refresh_ports).grid(row=0, column=2, padx=5)
        tk.Button(conn_frame, text="Connecter", command=self.connect, bg="green", fg="white").grid(row=0, column=3, padx=5)
        
        self.status_label = tk.Label(conn_frame, text="Déconnecté", fg="red", font=("Arial", 10, "bold"))
        self.status_label.grid(row=1, column=0, columnspan=4, pady=5)
        
        # === Grille 4×20 ===
        grid_frame = tk.LabelFrame(self.root, text="Séquenceur (Max 3 servos par ligne)", padx=10, pady=10)
        grid_frame.pack(padx=10, pady=10, fill="both", expand=True)
        
        # Headers
        headers = ["Servo 1", "Servo 2", "Servo 3", "Servo 4"]
        for col, header in enumerate(headers):
            tk.Label(grid_frame, text=header, font=("Arial", 10, "bold")).grid(row=0, column=col+1, padx=2, pady=5)
        
        # Grille de boutons
        for line in range(20):
            row_buttons = []
            
            # Numéro de ligne
            tk.Label(grid_frame, text=f"L{line+1}", font=("Arial", 9)).grid(row=line+1, column=0, padx=5)
            
            for col in range(4):
                btn = tk.Button(grid_frame, text="", width=8, height=3, bg="white",
                               command=lambda l=line, c=col: self.toggle_cell(l, c))
                btn.grid(row=line+1, column=col+1, padx=2, pady=2)
                row_buttons.append(btn)
            
            self.cell_buttons.append(row_buttons)
        
        # === Contrôles ===
        control_frame = tk.Frame(self.root, padx=10, pady=10)
        control_frame.pack(fill="x")
        
        self.line_label = tk.Label(control_frame, text=f"Ligne actuelle: {self.current_line + 1}/20", 
                                   font=("Arial", 14, "bold"), fg="blue")
        self.line_label.pack(pady=10)
        
        btn_frame = tk.Frame(control_frame)
        btn_frame.pack()
        
        tk.Button(btn_frame, text="⬆ UP", command=self.execute_up, 
                 font=("Arial", 16, "bold"), bg="lightblue", width=10, height=2).pack(side="left", padx=10)
        tk.Button(btn_frame, text="⬇ DOWN", command=self.execute_down,
                 font=("Arial", 16, "bold"), bg="lightcoral", width=10, height=2).pack(side="left", padx=10)
        
        tk.Button(control_frame, text="🔄 Réinitialiser tout", command=self.reset_grid,
                 bg="orange", fg="white", font=("Arial", 10)).pack(pady=10)
        
        # Highlight ligne actuelle
        self.highlight_current_line()
    
    def refresh_ports(self):
        ports = [port.device for port in serial.tools.list_ports.comports()]
        if ports:
            menu = self.port_menu["menu"]
            menu.delete(0, "end")
            for port in ports:
                menu.add_command(label=port, command=lambda p=port: self.port_var.set(p))
            self.port_var.set(ports[0])
    
    def connect(self):
        port = self.port_var.get()
        if not port:
            messagebox.showerror("Erreur", "Sélectionnez un port")
            return
        
        try:
            self.serial_conn = serial.Serial(port, 115200, timeout=1)
            import time
            time.sleep(3)
            self.status_label.config(text=f"Connecté: {port}", fg="green")
            messagebox.showinfo("Succès", "Connexion établie !")
        except Exception as e:
            messagebox.showerror("Erreur", f"Connexion impossible: {e}")
    
    def toggle_cell(self, line, col):
        # Vérifier la limite de 3 servos actifs
        active_count = sum(self.grid_state[line])
        
        if self.grid_state[line][col] == 0:  # Activation
            if active_count >= 3:
                messagebox.showwarning("Limite", "Maximum 3 servos par ligne !")
                return
            self.grid_state[line][col] = 1
            self.cell_buttons[line][col].config(bg="black", fg="white", text="✓")
        else:  # Désactivation
            self.grid_state[line][col] = 0
            self.cell_buttons[line][col].config(bg="white", fg="black", text="")
    
    def execute_line(self, line_num):
        if not self.serial_conn:
            messagebox.showerror("Erreur", "Pas de connexion Arduino")
            return
        
        states = self.grid_state[line_num]
        command = f"L{line_num+1},{states[0]},{states[1]},{states[2]},{states[3]}\n"
        
        try:
            self.serial_conn.write(command.encode())
            print(f"Envoyé: {command.strip()}")
        except Exception as e:
            messagebox.showerror("Erreur", f"Envoi impossible: {e}")
    
    def execute_up(self):
        if self.current_line < 19:
            self.execute_line(self.current_line)
            self.current_line += 1
            self.update_display()
        else:
            messagebox.showinfo("Info", "Dernière ligne atteinte")
    
    def execute_down(self):
        if self.current_line > 0:
            self.current_line -= 1
            self.execute_line(self.current_line)
            self.update_display()
        else:
            messagebox.showinfo("Info", "Première ligne atteinte")
    
    def update_display(self):
        self.line_label.config(text=f"Ligne actuelle: {self.current_line + 1}/20")
        self.highlight_current_line()
    
    def highlight_current_line(self):
        # Retirer l'ancien highlight
        for line in range(20):
            for col in range(4):
                if self.grid_state[line][col] == 1:
                    self.cell_buttons[line][col].config(bg="black")
                else:
                    self.cell_buttons[line][col].config(bg="white")
        
        # Ajouter le highlight sur la ligne actuelle
        for col in range(4):
            current_bg = self.cell_buttons[self.current_line][col].cget("bg")
            if current_bg == "white":
                self.cell_buttons[self.current_line][col].config(bg="lightyellow")
            else:
                self.cell_buttons[self.current_line][col].config(bg="darkgray")
    
    def reset_grid(self):
        if messagebox.askyesno("Confirmation", "Réinitialiser toute la grille ?"):
            self.grid_state = [[0 for _ in range(4)] for _ in range(20)]
            self.current_line = 0
            for line in range(20):
                for col in range(4):
                    self.cell_buttons[line][col].config(bg="white", fg="black", text="")
            self.update_display()

if __name__ == "__main__":
    root = tk.Tk()
    app = ServoSequencer(root)
    root.mainloop()