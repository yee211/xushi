package io.github.yee211.classschedule;

import static org.junit.Assert.*;
import android.content.Context;
import android.content.ContextWrapper;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import com.getcapacitor.JSObject;
import com.getcapacitor.PluginCall;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;
import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.junit.runner.RunWith;

@RunWith(AndroidJUnit4.class)
public class SavedAccountsTest {
    private File directory;
    private Context context;
    private SavedAccountsPlugin plugin;
    private static class Call extends PluginCall {
        JSObject result;
        String error;
        Call(String method, JSObject data) { super(null, "SavedAccounts", "test", method, data); }
        @Override public void resolve(JSObject data) { result = data; }
        @Override public void resolve() { result = new JSObject(); }
        @Override public void reject(String message) { error = message; }
    }
    private SavedAccountsPlugin instance() {
        return new SavedAccountsPlugin() { @Override public Context getContext() { return context; } };
    }
    @Before public void prepare() {
        Context original = InstrumentationRegistry.getInstrumentation().getTargetContext();
        directory = new File(original.getNoBackupFilesDir(), "accounts-test-" + UUID.randomUUID());
        assertTrue(directory.mkdir());
        context = new ContextWrapper(original) { @Override public File getNoBackupFilesDir() { return directory; } };
        plugin = instance();
    }
    @After public void cleanup() {
        for (File file : directory.listFiles()) file.delete();
        directory.delete();
    }
    private void save(String email, String password) {
        JSObject data = new JSObject(); data.put("email", email); data.put("password", password); data.put("username", "Test");
        Call call = new Call("save", data); plugin.save(call); assertNull(call.error);
    }
    private Call read(String email) {
        JSObject data = new JSObject(); data.put("email", email);
        Call call = new Call("read", data); plugin.read(call); return call;
    }
    @Test public void encryptedStorageSurvivesRestartAndListsNoPassword() throws Exception {
        save("USER@example.com", "test-secret-123");
        String disk = new String(Files.readAllBytes(new File(directory, "saved-accounts.enc").toPath()), StandardCharsets.UTF_8);
        assertFalse(disk.contains("test-secret-123")); assertFalse(disk.contains("example.com"));
        plugin = instance();
        assertEquals("test-secret-123", read("user@example.com").result.getString("password"));
        Call list = new Call("list", new JSObject()); plugin.list(list);
        assertEquals(1, list.result.getJSONArray("accounts").length());
        assertFalse(list.result.getJSONArray("accounts").getJSONObject(0).has("password"));
    }
    @Test public void updatedCredentialsReplaceAccountAndRetentionIsBounded() throws Exception {
        save("user@example.com", "old-password"); save("USER@example.com", "new-password");
        assertEquals("new-password", read("user@example.com").result.getString("password"));
        for (int i = 0; i < 6; i++) save("user" + i + "@example.com", "test-password");
        Call list = new Call("list", new JSObject()); plugin.list(list);
        assertEquals(5, list.result.getJSONArray("accounts").length());
        assertEquals("user5@example.com", list.result.getJSONArray("accounts").getJSONObject(0).getString("email"));
        assertNotNull(read("user@example.com").error);
    }
    @Test public void removeAndClearWorkIncludingCorruptStorage() throws Exception {
        save("user@example.com", "test-password");
        JSObject data = new JSObject(); data.put("email", "user@example.com"); plugin.remove(new Call("remove", data));
        assertNotNull(read("user@example.com").error);
        save("user@example.com", "test-password");
        Files.write(new File(directory, "saved-accounts.enc").toPath(), "invalid".getBytes(StandardCharsets.UTF_8));
        assertNotNull(read("user@example.com").error);
        JSObject all = new JSObject(); all.put("all", true);
        Call clear = new Call("remove", all); plugin.remove(clear); assertNull(clear.error);
        save("user@example.com", "new-password");
        assertEquals("new-password", read("user@example.com").result.getString("password"));
    }
}
