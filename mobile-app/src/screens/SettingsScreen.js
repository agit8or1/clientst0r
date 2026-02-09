import React from 'react';
import { View, StyleSheet, ScrollView } from 'react-native';
import { List, Avatar, Switch, Divider, Button } from 'react-native-paper';
import { useAuth } from '../contexts/AuthContext';

export default function SettingsScreen() {
  const { user, logout } = useAuth();
  const [darkMode, setDarkMode] = React.useState(true);
  const [notifications, setNotifications] = React.useState(true);
  const [biometrics, setBiometrics] = React.useState(false);

  const handleLogout = async () => {
    await logout();
  };

  return (
    <ScrollView style={styles.container}>
      <View style={styles.header}>
        <Avatar.Text
          size={80}
          label={user?.username?.substring(0, 2).toUpperCase() || 'U'}
          style={styles.avatar}
        />
        <List.Item
          title={user?.first_name && user?.last_name ? `${user.first_name} ${user.last_name}` : user?.username}
          description={user?.email || 'No email'}
          style={styles.userInfo}
        />
      </View>

      <List.Section>
        <List.Subheader>Appearance</List.Subheader>
        <List.Item
          title="Dark Mode"
          description="Use dark theme"
          left={(props) => <List.Icon {...props} icon="theme-light-dark" />}
          right={() => (
            <Switch value={darkMode} onValueChange={setDarkMode} />
          )}
          style={styles.listItem}
        />
      </List.Section>

      <Divider />

      <List.Section>
        <List.Subheader>Notifications</List.Subheader>
        <List.Item
          title="Push Notifications"
          description="Receive push notifications"
          left={(props) => <List.Icon {...props} icon="bell" />}
          right={() => (
            <Switch value={notifications} onValueChange={setNotifications} />
          )}
          style={styles.listItem}
        />
      </List.Section>

      <Divider />

      <List.Section>
        <List.Subheader>Security</List.Subheader>
        <List.Item
          title="Biometric Login"
          description="Use fingerprint or Face ID"
          left={(props) => <List.Icon {...props} icon="fingerprint" />}
          right={() => (
            <Switch value={biometrics} onValueChange={setBiometrics} />
          )}
          style={styles.listItem}
        />
        <List.Item
          title="Change Password"
          description="Update your password"
          left={(props) => <List.Icon {...props} icon="lock-reset" />}
          right={(props) => <List.Icon {...props} icon="chevron-right" />}
          onPress={() => {}}
          style={styles.listItem}
        />
      </List.Section>

      <Divider />

      <List.Section>
        <List.Subheader>About</List.Subheader>
        <List.Item
          title="Version"
          description="1.0.0"
          left={(props) => <List.Icon {...props} icon="information" />}
          style={styles.listItem}
        />
        <List.Item
          title="Terms of Service"
          left={(props) => <List.Icon {...props} icon="file-document" />}
          right={(props) => <List.Icon {...props} icon="chevron-right" />}
          onPress={() => {}}
          style={styles.listItem}
        />
        <List.Item
          title="Privacy Policy"
          left={(props) => <List.Icon {...props} icon="shield-account" />}
          right={(props) => <List.Icon {...props} icon="chevron-right" />}
          onPress={() => {}}
          style={styles.listItem}
        />
      </List.Section>

      <View style={styles.logoutContainer}>
        <Button
          mode="contained"
          onPress={handleLogout}
          icon="logout"
          style={styles.logoutButton}
          buttonColor="#dc3545"
        >
          Sign Out
        </Button>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0d1117',
  },
  header: {
    alignItems: 'center',
    paddingVertical: 40,
    backgroundColor: '#161b22',
  },
  avatar: {
    backgroundColor: '#0d6efd',
    marginBottom: 16,
  },
  userInfo: {
    backgroundColor: 'transparent',
  },
  listItem: {
    backgroundColor: '#161b22',
    marginBottom: 1,
  },
  logoutContainer: {
    padding: 20,
    paddingBottom: 40,
  },
  logoutButton: {
    paddingVertical: 8,
  },
});
