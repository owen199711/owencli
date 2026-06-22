package com.owencli.contextos;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties
public class ContextOsApplication {

    public static void main(String[] args) {
        SpringApplication.run(ContextOsApplication.class, args);
    }
}
