// Placeholder shell. The mobile client is a thin presentation layer: it sends
// participant messages to the Cairn API and shows Cairn's replies. It must never
// make journey decisions itself - those are deterministic and server-side.
import { StatusBar } from "expo-status-bar";
import { useEffect, useState } from "react";
import { StyleSheet, Text, View } from "react-native";
import Constants from "expo-constants";

const API_URL: string = (Constants.expoConfig?.extra?.apiUrl as string) ?? "http://localhost:8000";

export default function App() {
  const [status, setStatus] = useState("checking API...");

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => r.json())
      .then((body) => setStatus(`API ${body.status} (v${body.version})`))
      .catch(() => setStatus(`API unreachable at ${API_URL}`));
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Cairn</Text>
      <Text>{status}</Text>
      <StatusBar style="auto" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  title: { fontSize: 28, fontWeight: "600" },
});
