import { createContext, useContext, useEffect, useState, useCallback } from "react";
import { api } from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [status, setStatus] = useState("checking"); // checking | in | out
  const [username, setUsername] = useState(null);

  const refresh = useCallback(async () => {
    try {
      const data = await api.me();
      if (data.authenticated) {
        setStatus("in");
        setUsername(data.username);
      } else {
        setStatus("out");
        setUsername(null);
      }
    } catch {
      setStatus("out");
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = async (u, p) => {
    const data = await api.login(u, p);
    setStatus("in");
    setUsername(data.username);
  };

  const logout = async () => {
    try {
      await api.logout();
    } finally {
      setStatus("out");
      setUsername(null);
    }
  };

  return (
    <AuthContext.Provider value={{ status, username, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
