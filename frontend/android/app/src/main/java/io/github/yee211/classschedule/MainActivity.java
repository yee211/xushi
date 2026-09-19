package io.github.yee211.classschedule;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(AcademicWebviewPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
