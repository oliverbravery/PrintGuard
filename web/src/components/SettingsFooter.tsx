import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

const Slot = createContext<(note: ReactNode) => void>(() => {});

export function SettingsFooter({ children }: { children: (note: ReactNode) => ReactNode }) {
  const [note, setNote] = useState<ReactNode>(null);
  return <Slot.Provider value={setNote}>{children(note)}</Slot.Provider>;
}

export function useSettingsFooter(note: ReactNode): void {
  const setNote = useContext(Slot);
  useEffect(() => {
    setNote(note);
    return () => setNote(null);
  }, [note]);
}
