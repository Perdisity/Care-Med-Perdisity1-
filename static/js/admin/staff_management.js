document.addEventListener('DOMContentLoaded', () => {
    // 1. Setup Modals
    const createModal = document.getElementById('create-user-modal');
    const editModal = document.getElementById('edit-user-modal');
    
    // Create User Modal Logic
    const openCreateBtn = document.getElementById('open-modal-btn');
    const closeCreateBtn = document.getElementById('close-modal-btn');
    const createUserForm = createModal ? createModal.querySelector('form') : null;
    const createErrorBox = document.getElementById('create-user-error');
    const createSubmitBtn = document.getElementById('create-user-submit-btn');

    function showCreateError(msg) {
        if (createErrorBox) {
            createErrorBox.textContent = msg;
            createErrorBox.style.display = 'block';
        }
    }

    function clearCreateError() {
        if (createErrorBox) {
            createErrorBox.textContent = '';
            createErrorBox.style.display = 'none';
        }
    }

    if (openCreateBtn) {
        openCreateBtn.addEventListener('click', () => {
            clearCreateError();
            if (createUserForm) createUserForm.reset();
            createModal.classList.remove('hidden');
        });
    }
    if (closeCreateBtn) {
        closeCreateBtn.addEventListener('click', () => {
            clearCreateError();
            createModal.classList.add('hidden');
        });
    }

    if (createSubmitBtn && createUserForm) {
        createSubmitBtn.addEventListener('click', async () => {
            clearCreateError();
            createSubmitBtn.disabled = true;
            createSubmitBtn.textContent = 'Creating...';

            const formData = new FormData(createUserForm);
            try {
                const res = await fetch(createUserForm.action, {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();

                if (data.success) {
                    createModal.classList.add('hidden');
                    createUserForm.reset();
                    // Show success then reload so the table updates
                    alert(data.message);
                    location.reload();
                } else {
                    showCreateError(data.message);
                }
            } catch (err) {
                showCreateError('A network error occurred. Please try again.');
            } finally {
                createSubmitBtn.disabled = false;
                createSubmitBtn.textContent = 'Create User Account';
            }
        });
    }

    // Edit User Modal Logic
    const closeEditBtn = document.getElementById('close-edit-modal-btn');
    if (closeEditBtn) {
        closeEditBtn.addEventListener('click', () => editModal.classList.add('hidden'));
    }

    // 2. Table Event Delegation
    const staffTable = document.querySelector('.staff-data-table');
    if (staffTable) {
        staffTable.addEventListener('click', (e) => {
            // Handle Edit Click
            const editBtn = e.target.closest('.edit-user-btn');
            if (editBtn) {
                // Populate Basic Info
                document.getElementById('edit-user-id').value = editBtn.dataset.userId;
                document.getElementById('edit-user-role').value = editBtn.dataset.role;
                document.getElementById('edit-user-position').value = editBtn.dataset.position || '';
                document.getElementById('edit-user-name').innerText = 
                    `Editing: ${editBtn.dataset.firstName} ${editBtn.dataset.lastName}`;
                
                // Populate Permission Toggles
                const permissionFields = [
                    'can_manage_customers', 'can_verify_customers', 'can_manage_products',
                    'can_update_stock', 'can_process_transactions', 'can_confirm_payments',
                    'can_export_transactions', 'can_manage_expenses', 'can_view_reports',
                    'can_view_logs', 'can_view_active_rentals'
                ];

                permissionFields.forEach(field => {
                    const checkbox = editModal.querySelector(`input[name="${field}"]`);
                    if (checkbox) {
                        // Convert snake_case (can_manage_customers) to camelCase (canManageCustomers)
                        // because dataset attributes are automatically camelCased by the browser
                        const camelCaseField = field.replace(/_([a-z])/g, (g) => g[1].toUpperCase());
                        
                        // Check the attribute and compare to the string "true"
                        checkbox.checked = editBtn.dataset[camelCaseField] === 'true';
                    }
                });
                
                editModal.classList.remove('hidden');
            }
        });
    }

    // 3. Delete Form Submission Confirmation
    document.querySelectorAll('.delete-user-form').forEach(form => {
        form.addEventListener('submit', (e) => {
            if (!confirm('WARNING: This will remove access for this user. Are you sure?')) {
                e.preventDefault();
            }
        });
    });
});