import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import RomTranslator from "@/pages/RomTranslator";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<RomTranslator />} />
        </Routes>
      </BrowserRouter>
      <Toaster
        theme="dark"
        position="bottom-right"
        toastOptions={{
          style: {
            background: "#141414",
            border: "1px solid #262626",
            color: "#fafafa",
            fontFamily: "JetBrains Mono, monospace",
            borderRadius: "2px",
          },
        }}
      />
    </div>
  );
}

export default App;
