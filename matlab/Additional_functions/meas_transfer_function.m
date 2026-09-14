function variable_value = meas_transfer_function(current_value, previous_value, tau, T)
            % Funktion zur Berechnung des nächsten Werts basierend auf der Übertragungsfunktion
            %
            % Eingabewerte:
            % current_value  - Aktueller Eingangswert (z.B. pO2, cXL, pH)
            % previous_value - Vorheriger Ausgangswert (gemessener Wert)
            % K              - Verstärkungsfaktor der Übertragungsfunktion
            K = 1;
            % tau            - Zeitkonstante der Übertragungsfunktion
            % T              - Abtastzeit
            %
            % Ausgabewert:
            % next_value     - Berechneter nächster Ausgangswert (gemessener Wert)
            % Berechnung des nächsten Werts
            T = T / 3600; % Abtastzeit von sekunden in stunden umrechenen
            variable_value = previous_value + (T / tau) * (K * current_value - previous_value);
        end