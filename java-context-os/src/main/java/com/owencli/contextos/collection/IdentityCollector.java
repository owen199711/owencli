package com.owencli.contextos.collection;

import com.owencli.contextos.core.model.UserProfile;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.concurrent.CompletableFuture;

/**
 * Identity collector - reads user profile from env or injected value.
 */
public class IdentityCollector {

    private static final Logger log = LoggerFactory.getLogger(IdentityCollector.class);

    private final UserProfile userProfile;

    public IdentityCollector() {
        this(null);
    }

    public IdentityCollector(UserProfile userProfile) {
        this.userProfile = userProfile;
        if (userProfile != null) {
            log.info("IdentityCollector initialized with injected profile: user_id={}, role={}",
                    userProfile.getUserId(), userProfile.getRole());
        } else {
            log.info("IdentityCollector initialized (will read from env)");
        }
    }

    public CompletableFuture<UserProfile> collect() {
        log.debug("Collecting identity context...");

        if (userProfile != null) {
            log.info("Using injected user profile");
            return CompletableFuture.completedFuture(userProfile);
        }

        var profile = new UserProfile();
        profile.setUserId(getEnv("USER_ID", "anonymous"));
        profile.setRole(getEnv("USER_ROLE", "developer"));
        profile.setPermission(getEnv("USER_PERMISSION", "readonly"));
        profile.setLanguage(getEnv("USER_LANGUAGE", "zh-CN"));
        profile.setSkillLevel(getEnv("USER_SKILL_LEVEL", "intermediate"));
        profile.setOrganization(getEnv("ORG_NAME", null));
        profile.setTenant(getEnv("TENANT_ID", null));
        profile.setTeam(getEnv("TEAM_NAME", null));

        log.info("Identity collected: user_id={}, role={}, language={}",
                profile.getUserId(), profile.getRole(), profile.getLanguage());
        return CompletableFuture.completedFuture(profile);
    }

    private static String getEnv(String key, String defaultValue) {
        String val = System.getenv(key);
        return val != null && !val.isEmpty() ? val : defaultValue;
    }
}
