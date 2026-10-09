package io.github.yee211.classschedule;

import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import android.util.Base64;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONArray;
import org.json.JSONObject;

@CapacitorPlugin(name = "SavedAccounts")
public class SavedAccountsPlugin extends Plugin {
    private static final String KEY = "xushi.saved.accounts.v1";

    private AtomicFile file() {
        return new AtomicFile(new File(getContext().getNoBackupFilesDir(), "saved-accounts.enc"));
    }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(KEY)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(KEY, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(KEY, null);
    }

    private JSONArray accounts() throws Exception {
        AtomicFile target = file();
        if (!target.getBaseFile().exists()) return new JSONArray();
        JSONObject envelope = new JSONObject(new String(target.readFully(), StandardCharsets.UTF_8));
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, Base64.decode(envelope.getString("iv"), Base64.NO_WRAP)));
        return new JSONArray(new String(cipher.doFinal(Base64.decode(envelope.getString("data"), Base64.NO_WRAP)), StandardCharsets.UTF_8));
    }

    private void write(JSONArray accounts) throws Exception {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key());
        JSONObject envelope = new JSONObject();
        envelope.put("iv", Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP));
        envelope.put("data", Base64.encodeToString(cipher.doFinal(accounts.toString().getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP));
        AtomicFile target = file();
        FileOutputStream stream = target.startWrite();
        try {
            stream.write(envelope.toString().getBytes(StandardCharsets.UTF_8));
            target.finishWrite(stream);
        } catch (Exception error) {
            target.failWrite(stream);
            throw error;
        }
    }

    @PluginMethod
    public synchronized void list(PluginCall call) {
        try {
            JSONArray records = accounts();
            JSArray result = new JSArray();
            for (int i = 0; i < records.length(); i++) {
                JSONObject record = records.getJSONObject(i);
                JSObject metadata = new JSObject();
                metadata.put("email", record.getString("email"));
                metadata.put("username", record.optString("username"));
                result.put(metadata);
            }
            JSObject output = new JSObject();
            output.put("accounts", result);
            call.resolve(output);
        } catch (Exception error) { call.reject("无法读取已保存账号，请清除后重新保存"); }
    }

    @PluginMethod
    public synchronized void save(PluginCall call) {
        String email = call.getString("email", "").trim().toLowerCase(java.util.Locale.ROOT);
        String password = call.getString("password", "");
        if (email.isEmpty() || email.length() > 254 || password.length() < 6 || password.length() > 72) {
            call.reject("登录信息无效"); return;
        }
        try {
            JSONArray previous = accounts();
            JSONArray next = new JSONArray();
            JSONObject record = new JSONObject();
            record.put("email", email);
            record.put("password", password);
            record.put("username", call.getString("username", ""));
            next.put(record);
            for (int i = 0; i < previous.length() && next.length() < 5; i++) {
                JSONObject item = previous.getJSONObject(i);
                if (!email.equals(item.getString("email"))) next.put(item);
            }
            write(next);
            call.resolve();
        } catch (Exception error) { call.reject("账号保存失败，请重新尝试"); }
    }

    @PluginMethod
    public synchronized void read(PluginCall call) {
        try {
            JSONArray records = accounts();
            for (int i = 0; i < records.length(); i++) {
                JSONObject record = records.getJSONObject(i);
                if (record.getString("email").equals(call.getString("email"))) {
                    JSObject output = new JSObject();
                    output.put("email", record.getString("email"));
                    output.put("password", record.getString("password"));
                    call.resolve(output); return;
                }
            }
            call.reject("账号已移除，请重新输入邮箱和密码");
        } catch (Exception error) { call.reject("无法读取登录信息，请重新输入邮箱和密码"); }
    }

    @PluginMethod
    public synchronized void remove(PluginCall call) {
        try {
            if (call.getBoolean("all", false)) { file().delete(); call.resolve(); return; }
            JSONArray records = accounts();
            JSONArray next = new JSONArray();
            for (int i = 0; i < records.length(); i++) {
                JSONObject record = records.getJSONObject(i);
                if (!record.getString("email").equals(call.getString("email"))) next.put(record);
            }
            if (next.length() == 0) file().delete();
            else write(next);
            call.resolve();
        } catch (Exception error) { call.reject("移除账号失败，请重试"); }
    }
}
