#[derive(Debug, Clone)]
pub struct UserAccount {
    pub username: String,
    pub uid: u32,
    pub gid: u32,
    pub home_dir: String,
}

#[derive(Debug, Default)]
pub struct SystemAdminManager {
    users: Vec<UserAccount>,
}

impl SystemAdminManager {
    pub fn new() -> Self { Self::default() }
    pub fn create_user(&mut self, name: &str, uid: u32, gid: u32) {
        self.users.push(UserAccount {
            username: name.to_string(),
            uid,
            gid,
            home_dir: format!("/home/{}", name),
        });
    }
    pub fn user_exists(&self, name: &str) -> bool { self.users.iter().any(|u| u.username == name) }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_system_admin_user_creation() {
        let mut admin = SystemAdminManager::new();
        admin.create_user("operator", 1000, 1000);
        assert!(admin.user_exists("operator"));
        assert!(!admin.user_exists("guest"));
    }
}
